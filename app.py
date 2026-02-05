import streamlit as st
import pandas as pd
import time
import hashlib
import hmac
import base64
import requests
import plotly.express as px
from datetime import datetime, timedelta

# --- 1. 네이버 API 호출 최적화 (일괄 조회 방식) ---
def generate_signature(timestamp, method, uri, secret_key):
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(bytes(secret_key, "utf-8"), bytes(message, "utf-8"), hashlib.sha256)
    return base64.b64encode(hash.digest()).decode()

def get_naver_search_vols_bulk(keywords, api_key, secret_key, customer_id):
    """최대 5개 키워드를 한 번에 조회하여 속도 개선"""
    BASE_URL = 'https://api.searchad.naver.com'
    uri = '/keywordstool'
    method = 'GET'
    timestamp = str(round(time.time() * 1000))
    signature = generate_signature(timestamp, method, uri, secret_key)
    headers = {'X-Timestamp': timestamp, 'X-API-KEY': api_key, 'X-Customer': customer_id, 'X-Signature': signature}
    
    # 리스트를 쉼표로 연결하여 한 번에 요청
    params = {'hintKeywords': ",".join(keywords[:5]), 'showDetail': '1'}
    vols = {}
    try:
        res = requests.get(BASE_URL + uri, params=params, headers=headers).json()
        if 'keywordList' in res:
            for item in res['keywordList']:
                pc = str(item['monthlyPcQcCnt']).replace('< ', '10')
                mo = str(item['monthlyMobileQcCnt']).replace('< ', '10')
                vols[item['relKeyword']] = int(pc) + int(mo)
    except: pass
    return vols

def get_datalab_trend(keyword, client_id, client_secret, start_date, end_date, time_unit):
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret, "Content-Type": "application/json"}
    unit_map = {"일자별": "date", "주차별": "week", "월별": "month"}
    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "timeUnit": unit_map[time_unit],
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}]
    }
    try:
        res = requests.post(url, headers=headers, json=body).json()
        if 'results' in res:
            return {d['period']: d['ratio'] for d in res['results'][0]['data']}
    except: pass
    return {}

# --- 2. 데이터 로딩 (캐싱 강화) ---
@st.cache_data(ttl=3600)
def load_all_data(sheet_id):
    main_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    preset_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=PRESETS"
    
    m_df = pd.read_csv(main_url)
    m_df.columns = [c.strip().upper() for c in m_df.columns]
    
    try:
        p_df = pd.read_csv(preset_url)
        p_df.columns = [c.strip().upper() for c in p_df.columns]
        presets = {str(row.filter(like='NAME').values[0]).strip(): 
                   [i.strip() for i in str(row.filter(like='KEYWORD').values[0]).split(',')] 
                   for _, row in p_df.iterrows()}
    except:
        presets = {}
    return m_df, presets

# --- 3. 메인 UI ---
st.set_page_config(page_title="시디즈 고속 분석 센터", layout="wide")

try:
    keys = {k: st.secrets[k.upper()] for k in ["naver_api_key", "naver_secret_key", "naver_customer_id", "naver_client_id", "naver_client_secret"]}
except:
    st.error("Secrets 설정 오류"); st.stop()

with st.sidebar:
    sid = st.text_input("Sheet ID", "1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    unit = st.radio("단위", ["일자별", "주차별", "월별"], index=2)
    dates = st.date_input("기간", [datetime(2024, 12, 1), datetime(2025, 1, 31)])
    if st.button("🔄 시트 새로고침"): st.cache_data.clear(); st.rerun()

master_df, presets = load_all_data(sid)

if 'active_kws' not in st.session_state: st.session_state.active_kws = []
if 'p_name' not in st.session_state: st.session_state.p_name = ""

st.title("🚀 시디즈 고속 마켓쉐어 분석")

# --- 4. 프리셋 선택 ---
if presets:
    cols = st.columns(5)
    for i, (name, items) in enumerate(presets.items()):
        if cols[i % 5].button(name, use_container_width=True):
            matched = master_df[master_df['GROUP'].isin(items) | master_df['KEYWORD'].isin(items)]
            st.session_state.active_kws = matched['KEYWORD'].unique().tolist()
            st.session_state.p_name = name
            st.rerun()

# --- 5. 분석 로직 (최적화) ---
if st.session_state.active_kws:
    st.info(f"선택됨: {st.session_state.p_name} ({len(st.session_state.active_kws)}개 키워드)")
    
    if st.button("📊 분석 시작", type="primary"):
        results = []
        kws = st.session_state.active_kws
        progress = st.progress(0)
        status = st.empty()
        
        # 1. 광고 API 검색량 먼저 벌크 조회 (속도 핵심)
        status.text("✅ 검색량 동시 조회 중...")
        all_vols = {}
        for i in range(0, len(kws), 5):
            chunk = kws[i:i+5]
            all_vols.update(get_naver_search_vols_bulk(chunk, keys["naver_api_key"], keys["naver_secret_key"], keys["naver_customer_id"]))
            progress.progress(min((i+5)/(len(kws)*2), 0.5))
        
        # 2. 데이터랩 트렌드 조회
        for idx, kw in enumerate(kws):
            status.text(f"⏳ 트렌드 분석 중: {kw} ({idx+1}/{len(kws)})")
            vol = all_vols.get(kw, 0)
            trends = get_datalab_trend(kw, keys["naver_client_id"], keys["naver_client_secret"], dates[0], dates[1], unit)
            
            if trends:
                total_r = sum(trends.values())
                brand = master_df[master_df['KEYWORD'] == kw]['GROUP'].values[0]
                for p, r in trends.items():
                    results.append({"브랜드": brand, "기간": p, "키워드": kw, "검색량": int((r/total_r)*vol) if total_r>0 else 0})
            progress.progress(0.5 + (idx+1)/(len(kws)*2))
        
        status.empty(); progress.empty()

        if results:
            df = pd.DataFrame(results)
            df_grp = df.groupby(['기간', '브랜드'])['검색량'].sum().reset_index()
            df_grp['비중'] = (df_grp['검색량'] / df_grp.groupby('기간')['검색량'].transform('sum') * 100).round(1)
            
            fig = px.bar(df_grp, x="검색량", y="기간", color="브랜드", orientation='h', barmode='stack',
                         text=df_grp.apply(lambda x: f"{x['검색량']:,} ({x['비중']}%)", axis=1), height=600)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df.pivot_table(index=["브랜드", "키워드"], columns="기간", values="검색량", aggfunc="sum"))
