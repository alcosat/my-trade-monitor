import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
import os
from datetime import datetime
import zoneinfo
from typing import Dict, List, Tuple
from streamlit_autorefresh import st_autorefresh

# Настройка на уеб страницата
st.set_page_config(page_title="SMART AMFC Monitor", page_icon="🎯", layout="wide")

# --- СТАБИЛЕН ТАЙМЕР ЗА ПРЕЗАРЕЖДАНЕ ---
# Опресняваме страницата на всеки 5 минути (300 000 милисекунди),
# за да може кодът да засича новите свещи веднага след затварянето им.
st_autorefresh(interval=300000, key="amfcrefresh_stable")

CONFIG_FILE = "smart_amfc_monitor_config.json"

DEFAULT_INDICATORS = {
    'aroon_period': 14,
    'cmf_period': 20,
    'flow_buffer': 0.05,
    'confirm_bars': 5,
    'sl_atr_mult': 1.5,
    'tp1_r': 1.0, 'tp2_r': 2.0, 'tp3_r': 3.0
}

def load_config_static():
    default_config = {
        'symbols': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'],
        **DEFAULT_INDICATORS,
        'bot_token': '', 'chat_id': ''
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'symbols' in data and isinstance(data['symbols'], list) and len(data['symbols']) > 0:
                    return {**default_config, **data}
        except:
            pass
    return default_config

# Зареждане на конфигурацията в RAM на сесията
if 'runtime_cfg' not in st.session_state:
    st.session_state.runtime_cfg = load_config_static()
if 'previous_states' not in st.session_state:
    st.session_state.previous_states = {}
if 'scan_count' not in st.session_state:
    st.session_state.scan_count = 0

st.session_state.scan_count += 1
cfg = st.session_state.runtime_cfg

# --- СТРАНИЧЕН ПАНЕЛ ---
st.sidebar.title("⚙️ Настройки на Системата")

st.sidebar.subheader("📊 Параметри Индикатори")
cfg['aroon_period'] = st.sidebar.number_input("Aroon период", min_value=2, max_value=200, value=int(cfg['aroon_period']))
cfg['cmf_period'] = st.sidebar.number_input("CMF период", min_value=2, max_value=200, value=int(cfg['cmf_period']))
cfg['flow_buffer'] = st.sidebar.number_input("Flow Buffer", min_value=0.0, max_value=0.5, value=float(cfg['flow_buffer']), step=0.01)
cfg['confirm_bars'] = st.sidebar.number_input("Прозорец потвърждение (барове)", min_value=1, max_value=20, value=int(cfg['confirm_bars']))

st.sidebar.subheader("📐 Риск Мениджмънт (ATR)")
cfg['sl_atr_mult'] = st.sidebar.number_input("Stop Loss ATR множител", min_value=0.1, value=float(cfg['sl_atr_mult']), step=0.1)
cfg['tp1_r'] = st.sidebar.number_input("TP1 (R множител)", min_value=0.1, value=float(cfg['tp1_r']), step=0.1)
cfg['tp2_r'] = st.sidebar.number_input("TP2 (R множител)", min_value=0.1, value=float(cfg['tp2_r']), step=0.1)
cfg['tp3_r'] = st.sidebar.number_input("TP3 (R множител)", min_value=0.1, value=float(cfg['tp3_r']), step=0.1)

col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("💾 Приложи"):
        st.session_state.runtime_cfg = cfg
        st.success("Приложено!")
with col2:
    if st.button("🔄 Фабрични"):
        for key, val in DEFAULT_INDICATORS.items():
            cfg[key] = val
        st.session_state.runtime_cfg = cfg
        st.rerun()

# --- ЧИСТА МАТЕМАТИЧЕСКА ЛОГИКА ---
def get_klines(symbol: str, timeframe: str) -> pd.DataFrame:
    tf_mapping = {'15m': '15min', '1h': '60min', '4h': '4hour', '1d': '1day'}
    try:
        url = "https://huobi.pro"
        params = {'symbol': symbol.lower(), 'period': tf_mapping.get(timeframe, '60min'), 'size': 150}
        res = requests.get(url, params=params, timeout=10).json()
        if res.get('status') == 'ok':
            df = pd.DataFrame([{
                'timestamp': pd.to_datetime(k['id'], unit='s'), 'open': float(k['open']),
                'high': float(k['high']), 'low': float(k['low']), 'close': float(k['close']), 'volume': float(k['vol'])
            } for k in res['data']])
            return df.sort_values('timestamp').reset_index(drop=True)
    except:
        pass
    return pd.DataFrame()

def calculate_amfc(df: pd.DataFrame) -> Tuple[float, float, float]:
    aroon_len = int(cfg['aroon_period'])
    cmf_len = int(cfg['cmf_period'])
    if len(df) < max(aroon_len, cmf_len) + 5:
        return np.nan, np.nan, np.nan
        
    highs = df['high'].values
    lows = df['low'].values
    window_h = highs[-(aroon_len + 1):]
    window_l = lows[-(aroon_len + 1):]
    
    hb = aroon_len - np.argmax(window_h)
    lb = aroon_len - np.argmin(window_l)
    
    aroon_up = 100.0 * (aroon_len - hb) / aroon_len
    aroon_down = 100.0 * (aroon_len - lb) / aroon_len
    aroon_osc = aroon_up - aroon_down

    hl = df['high'] - df['low']
    mfv = np.where(hl > 0, ((2 * df['close'] - df['high'] - df['low']) / hl) * df['volume'], 0.0)
    vv = np.where(hl > 0, df['volume'], 0.0)
    cmf = (pd.Series(mfv).rolling(cmf_len).sum() / pd.Series(vv).rolling(cmf_len).sum()).iloc[-1]
    
    high_low = df['high'] - df['low']
    high_cp = np.abs(df['high'] - df['close'].shift())
    low_cp = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    
    return float(aroon_osc), float(cmf), float(atr)

def send_telegram_message(msg: str):
    if cfg.get('bot_token') and cfg.get('chat_id'):
        try:
            url = f"https://telegram.org{cfg['bot_token']}/sendMessage"
            requests.get(url, params={'chat_id': cfg['chat_id'], 'text': msg, 'parse_mode': 'HTML'}, timeout=10)
        except:
            pass

# --- ГЛАВЕН УЕБ ИНТЕРФЕЙС ---
st.title("🎯 SMART AMFC Конзолен Монитор")

# Добавяне на нови валути директно на сайта
new_symbol = st.text_input("➕ Добави нов актив временно (напр. SOLUSDT):").strip().upper()
if new_symbol and new_symbol not in cfg['symbols']:
    cfg['symbols'].append(new_symbol)
    st.session_state.runtime_cfg = cfg
    st.rerun()

# Времеви параметри за визуализация
now = datetime.now(zoneinfo.ZoneInfo("Europe/Sofia"))
bg_time = now.strftime('%H:%M:%S')

output_text = f"🔄 Сканиране #{st.session_state.scan_count} - {bg_time} (Българско време)\n"
output_text += "────────────────────────────────────────────────────────────────────────────────\n"

if 'symbols' not in cfg or not cfg['symbols']:
    output_text += "\nВ момента няма заредени активи в паметта.\n"
else:
    for symbol in cfg['symbols']:
        output_text += f"\n📊 {symbol}\n"
        output_text += "───────────────────────────────────────────────────────────────────────────\n"
        output_text += f"{'TF':5s} | {'PRICE':>12s} | {'AROON OSC':>9s} | {'CMF':>7s} | {'ATR':>9s} | СЪСТОЯНИЕ / СИГНАЛ\n"
        output_text += "──────┼──────────────┼───────────┼─────────┼─────────┼──────────────────────────\n"
        
        df_15m = get_klines(symbol, '15m')
        
        for tf in ['15m', '1h', '4h', '1d']:
            df = get_klines(symbol, tf) if tf != '15m' else df_15m
            if df.empty:
                output_text += f"{tf:5s} | {'Липса на данни':^57s}\n"
                continue
                
            aroon, cmf, atr = calculate_amfc(df)
            price = df['close'].iloc[-1]
            
            price_str = f"${price:,.2f}" if price >= 1 else f"${price:,.4f}"
            atr_str = f"{atr:,.2f}" if atr >= 1 else f"{atr:,.4f}"
            aroon_str = f"{aroon:+5.1f}"
            cmf_str = f"{cmf:+5.2f}"
            
            bias_txt = "Неутрален"
            if aroon > 0 and cmf > float(cfg['flow_buffer']): 
                bias_txt = "📈 Силно Купуване (Buying)"
            elif aroon < 0 and cmf < -float(cfg['flow_buffer']): 
                bias_txt = "📉 Силно Продаване (Selling)"
                
            state_key = (symbol, tf)
            prev_bias = st.session_state.previous_states.get(state_key, 'NEUTRAL')
            current_bias_type = 'LONG' if '📈' in bias_txt else 'SHORT' if '📉' in bias_txt else 'NEUTRAL'
            
            if current_bias_type != prev_bias and current_bias_type != 'NEUTRAL':
                risk = atr * float(cfg['sl_atr_mult'])
                sl = price - risk if current_bias_type == 'LONG' else price + risk
                tp1 = price + (risk * float(cfg['tp1_r'])) if current_bias_type == 'LONG' else price - (risk * float(cfg['tp1_r']))
                tp2 = price + (risk * float(cfg['tp2_r'])) if current_bias_type == 'LONG' else price - (risk * float(cfg['tp2_r']))
                tp3 = price + (risk * float(cfg['tp3_r'])) if current_bias_type == 'LONG' else price - (risk * float(cfg['tp3_r']))
                
                emoji = "🟢" if current_bias_type == 'LONG' else "🔴"
                sig_txt = "BUY" if current_bias_type == 'LONG' else "SELL"
                
                msg = f"{emoji} <b>{symbol} – {sig_txt} СИГНАЛ</b> {emoji}\n"
                msg += "──────────────────\n"
                msg += f"💰 <b>Вход (Цена):</b> {price_str}\n"
                msg += f"📊 <b>Таймфрейм:</b> {tf}\n"
                msg += f"📊 <b>Aroon:</b> {aroon_str} | <b>CMF:</b> {cmf_str}\n"
                msg += "──────────────────\n"
                msg += "📐 <b>УПРАВЛЕНИЕ НА РИСКА (ATR):</b>\n"
                msg += f"🛑 SL: ${sl:.2f}\n"
                msg += f"🎯 TP1: ${tp1:.2f}\n"
                msg += f"🎯 TP2: ${tp2:.2f}\n"
                msg += f"🎯 TP3: ${tp3:.2f}\n"
                msg += f"\n⏰ Време: {bg_time}"
                
                send_telegram_message(msg)
                bias_txt += " 💥 [СИГНАЛ ИЗПРАТЕН]"
                
            st.session_state.previous_states[state_key] = current_bias_type
            
            output_text += f"{tf:5s} | {price_str:>12s} | {aroon_str:>9s} | {cmf_str:>7s} | {atr_str:>9s} | {bias_txt}\n"
        output_text += "───────────────────────────────────────────────────────────────────────────\n"

# Извеждане на състоянието в моношишинен лог
