import streamlit as st
import pandas as pd
import numpy as np
import requests
import json
import os
from datetime import datetime
import zoneinfo  # Библиотека за управление на часовите зони
from typing import Dict, List, Tuple
# Добавяме библиотеката за автоматично уеб опресняване
from streamlit_autorefresh import st_autorefresh

# Настройка на уеб страницата
st.set_page_config(page_title="SMART AMFC Monitor", page_icon="🎯", layout="wide")

# --- ИНТЕЛЕГЕНТЕН ТАЙМЕР ЗА КРЪГЪЛ ЧАС (БЪЛГАРСКО ВРЕМЕ) ---
now = datetime.now(zoneinfo.ZoneInfo("Europe/Sofia"))
current_minute = now.minute
current_second = now.second

minutes_to_next = 15 - (current_minute % 15)
total_seconds_to_wait = (minutes_to_next * 60) - current_second

if total_seconds_to_wait <= 0:
    total_seconds_to_wait = 900

st_autorefresh(interval=total_seconds_to_wait * 1000, key="amfcrefresh")
# ──────────────────────────────────────────────────────────

CONFIG_FILE = "smart_amfc_monitor_config.json"

DEFAULT_INDICATORS = {
    'aroon_period': 14,
    'cmf_period': 20,
    'flow_buffer': 0.05,
    'confirm_bars': 5,
    'sl_atr_mult': 1.5,
    'tp1_r': 1.0, 'tp2_r': 2.0, 'tp3_r': 3.0
}

def load_config():
    default_config = {
        'symbols': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'],
        **DEFAULT_INDICATORS,
        'bot_token': '', 'chat_id': ''
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return {**default_config, **json.load(f)}
        except:
            return default_config
    return default_config

def save_config(config_data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)

if 'config' not in st.session_state:
    st.session_state.config = load_config()
if 'previous_states' not in st.session_state:
    st.session_state.previous_states = {}

cfg = st.session_state.config

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
    if st.button("💾 Запази"):
        save_config(cfg)
        st.success("Запазено!")

with col2:
    if st.button("🔄 Фабрични"):
        for key, val in DEFAULT_INDICATORS.items():
            cfg[key] = val
        save_config(cfg)
        st.sidebar.warning("Възстановени фабрични настройки!")
        st.rerun()

# --- КЛИЕНТ ЗА ДАННИ (ОБНОВЕН ЗА GATE.IO - СВОБОДЕН ДОСТЪП ОТ RENDER) ---
def get_klines(symbol: str, timeframe: str) -> pd.DataFrame:
    tf_mapping = {'15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d'}
    
    # Gate.io изисква формат с долна черта, например BTC_USDT
    formatted_symbol = symbol.upper()
    if 'USDT' in formatted_symbol and '_' not in formatted_symbol:
        formatted_symbol = formatted_symbol.replace('USDT', '_USDT')
        
    try:
        url = "https://gateio.ws"
        params = {
            'currency_pair': formatted_symbol,
            'interval': tf_mapping.get(timeframe, '1h'),
            'limit': 150
        }
        
        res = requests.get(url, params=params, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                # Структура на Gate.io: [Unix, Обем, Close, High, Low, Open]
                df = pd.DataFrame([{
                    'timestamp': pd.to_datetime(float(k[0]), unit='s'),
                    'volume': float(k[1]),
                    'close': float(k[2]),
                    'high': float(k[3]),
                    'low': float(k[4]),
                    'open': float(k[5])
                } for k in data[::-1]])  # Реверсираме масива, за да съвпадне с логиката на изчисление
                return df
        else:
            # Алтернативен ендпойнт в случай на локален лимит
            url_alt = f"https://gateapi.io{formatted_symbol}"
            params_alt = {'convert_str': '1', 'type': tf_mapping.get(timeframe, '1h'), 'size': 150}
            res_alt = requests.get(url_alt, params=params_alt, timeout=10)
            if res_alt.status_code == 200:
                data_alt = res_alt.json().get('data', [])
                if data_alt:
                    df = pd.DataFrame([{
                        'timestamp': pd.to_datetime(float(k[0]), unit='ms'),
                        'open': float(k[1]),
                        'high': float(k[2]),
                        'low': float(k[3]),
                        'close': float(k[4]),
                        'volume': float(k[5])
                    } for k in data_alt[::-1]])
                    return df
    except:
        pass
    return pd.DataFrame()

def calculate_amfc(df: pd.DataFrame) -> Tuple[float, float, float]:
    aroon_len = cfg['aroon_period']
    cmf_len = cfg['cmf_period']
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
    if cfg['bot_token'] and cfg['chat_id']:
        try:
            url = f"https://telegram.org{cfg['bot_token']}/sendMessage"
            requests.get(url, params={'chat_id': cfg['chat_id'], 'text': msg, 'parse_mode': 'HTML'}, timeout=10)
        except:
            pass

# --- ГЛАВЕН УЕБ ИНТЕРФЕЙС ---
st.title("🎯 SMART AMFC Пазарно Табло")
bg_time = datetime.now(zoneinfo.ZoneInfo("Europe/Sofia")).strftime('%H:%M:%S')
st.write(f"Последно автоматично сканиране: **{bg_time}** (Българско време)")
st.info(f"Ботът е синхронизиран! Следващо точно пазарно сканиране след {minutes_to_next} мин.")

new_symbol = st.text_input("➕ Добави нов актив временно (напр. SOLUSDT):").strip().upper()
if new_symbol and new_symbol not in cfg['symbols']:
    cfg['symbols'].append(new_symbol)
    save_config(cfg)
    st.rerun()

st.write("### 📈 Текущи Пазарни Резултати")

for symbol in cfg['symbols']:
    st.markdown(f"#### 🔍 {symbol}")
    cols = st.columns(4)
    
    for idx, tf in enumerate(['15m', '1h', '4h', '1d']):
        df = get_klines(symbol, tf)
        if df.empty:
            cols[idx].error(f"{tf}: Грешка при извличане от Gate.io")
            continue
            
        aroon, cmf, atr = calculate_amfc(df)
        price = df['close'].iloc[-1]
        price_fmt = f"${price:.2f}" if price >= 1 else f"${price:.4f}"
        
        bias = '⚪ Неутрален'
        if aroon > 0 and cmf > cfg['flow_buffer']: bias = '🟢 Бичи тренд'
        elif aroon < 0 and cmf < -cfg['flow_buffer']: bias = '🔴 Мечи тренд'
        
        with cols[idx]:
            st.metric(label=f"Времева рамка {tf}", value=price_fmt)
            st.write(f"**Състояние:** {bias}")
            st.write(f"Aroon: `{aroon:+.1f}` | CMF: `{cmf:+.2f}`")
            
            state_key = (symbol, tf)
            prev_bias = st.session_state.previous_states.get(state_key, 'NEUTRAL')
            current_bias_type = 'LONG' if '🟢' in bias else 'SHORT' if '🔴' in bias else 'NEUTRAL'
            
            if current_bias_type != prev_bias and current_bias_type != 'NEUTRAL':
                risk = atr * cfg['sl_atr_mult']
                
                if current_bias_type == 'LONG':
                    sl = price - risk
                    tp1 = price + (risk * cfg['tp1_r'])
                    tp2 = price + (risk * cfg['tp2_r'])
                    tp3 = price + (risk * cfg['tp3_r'])
                else:  # SHORT
                    sl = price + risk
                    tp1 = price - (risk * cfg['tp1_r'])
                    tp2 = price - (risk * cfg['tp2_r'])
                    tp3 = price - (risk * cfg['tp3_r'])
                
                st.session_state.previous_states[state_key] = current_bias_type
                
                msg_text = (
                    f"🔔 <b>НОВ СИГНАЛ: {symbol} ({tf})</b>\n"
                    f"Посока: {bias}\n"
                    f"Входна цена: {price_fmt}\n"
