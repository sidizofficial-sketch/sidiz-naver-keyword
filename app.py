import streamlit as st
import pandas as pd
import time
import hashlib
import hmac
import base64
import requests
import plotly.express as px
from datetime import datetime

# --- 1. 네이버 API 호출 함수 ---
def generate_signature(timestamp, method, uri, secret_key):
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(bytes(secret_key, "utf-8"), bytes(message, "utf-8"), hashlib.sha256)
    return base64.b64encode(hash.digest()).decode()

def get_naver_search_vols_bulk(keywords, api_key, secret_key, customer_id):
    BASE_URL = 'https://api.searchad.naver.com'
    uri = '/keywordstool'
    method = 'GET'
    timestamp = str(round(time.time() * 1000))
    signature = generate_signature(timestamp, method, uri, secret_key)
    headers = {'X-Timestamp': timestamp, 'X-API-KEY': api_key, 'X-Customer': customer_id, 'X-Signature': signature}
    params = {'hintKeywords': ",".join(keywords[:5]), 'showDetail': '1'}
    vols = {}
    try:
        res = requests.get(BASE_URL + uri, params=params, headers=headers, timeout=5).json()
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
        "timeUnit": unit_map.get(time_unit, "month"),
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}]
    }
    try:
        res = requests.post(url, headers=headers, json=body, timeout=5).json()
        if 'results' in res:
            return {d['period']: d['ratio'] for d in res['results'][0]['data']}
    except: pass
    return {}

# --- 2. 데이터 로딩 ---
@st.cache_data(ttl=600)
def load_all_data(sheet_id):
    main_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    preset_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=PRESETS"
    m_df = pd.read_csv(main_url)
    m_df.columns = [c.strip().upper() for c in m_df.columns]
    try:
        p_df = pd.read_csv(preset_url)
        p_df.columns = [c.strip().upper() for c in p_df.columns]
        presets = {}
        name_col = [c for c in p_df.columns if 'NAME' in c][0]
        kw_col = [c for c in p_df.columns if 'KEYWORD' in c][0]
        for _, row in p_df.iterrows():
            presets[str(row[name_col]).strip()] = [i.strip() for i in str(row[kw_col]).split(',')]
    except: presets = {}
    return m_df, presets

# --- 3. UI 및 설정 ---
st.set_page_config(page_title="시디즈 통합 분석 센터", layout="wide")

try:
    keys = {k: st.secrets[k.upper()] for k in ["naver_api_key", "naver_secret_key", "naver_customer_id", "naver_client_id", "naver_client_secret"]}
except:
    st.error("Secrets 설정 오류"); st.stop()

with st.sidebar:
    st.header("⚙️ 분석 설정")
    sid = st.text_input("Sheet ID", "1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    unit = st.radio("단위", ["일자별", "주차별", "월별"], index=2)
    s_date = st.date_input("시작일", datetime(2024, 12, 1))
    e_date = st.date_input("종료일", datetime(2025, 1, 31))
    if st.button("🔄 전체 데이터 새로고침"):
        st.cache_data.clear(); st.rerun()

master_df, presets = load_all_data(sid)

# 세션 상태 초기화
if 'selected_kws' not in st.session_state: st.session_state.selected_kws = []

st.title("🚀 시디즈 마켓쉐어 분석 (프리셋+직접선택)")

# --- 4. 프리셋 버튼 섹션 ---
if presets:
    st.subheader("⚡ 퀵 분석 프리셋")
    p_cols = st.columns(5)
    for i, (name, items) in enumerate(presets.items()):
        if p_cols[i % 5].button(name, key=f"p_{i}", use_container_width=True):
            # 프리셋 클릭 시 해당 그룹의 키워드들을 선택 리스트에 업데이트
            matched = master_df[master_df['GROUP'].isin(items) | master_df['KEYWORD'].isin(items)]
            st.session_state.selected_kws = matched['KEYWORD'].unique().tolist()
            st.rerun()

# --- 5. 키워드 직접 선택 섹션 (며칠 전 버전 기능) ---
st.markdown("---")
st.subheader("🔍 분석 키워드 직접 선택")
all_kw_options = sorted(master_df['KEYWORD'].unique().tolist())
final_kws = st.multiselect(
    "분석할 키워드들을 선택하거나 프리셋 버튼을 누르세요.",
    options=all_kw_options,
    default=st.session_state.selected_kws,
    key="kw_selector"
)

# --- 6. 분석 실행 ---
if final_kws:
    if st.button("📊 선택한 키워드 분석 시작", type="primary"):
        results = []
        progress = st.progress(0)
        status = st.empty()
        
        # 단계 1: 검색량 조회
        all_vols = {}
        for i in range(0, len(final_kws), 5):
            chunk = final_kws[i:i+5]
            status.text(f"🔍 검색량 조회 중... ({i+len(chunk)}/{len(final_kws)})")
            all_vols.update(get_naver_search_vols_bulk(chunk, keys["naver_api_key"], keys["naver_secret_key"], keys["naver_customer_id"]))
            progress.progress(min((i+5)/(len(final_kws)*2), 0.5))
            time.sleep(0.1)
        
        # 단계 2: 트렌드 조회
        for idx, kw in enumerate(final_kws):
            status.text(f"⏳ 트렌드 수집 중: {kw} ({idx+1}/{len(final_kws)})")
            vol = all_vols.get(kw, 0)
            trends = get_datalab_trend(kw, keys["naver_client_id"], keys["naver_client_secret"], s_date, e_date, unit)
            if trends:
                total_r = sum(trends.values())
                brand_row = master_df[master_df['KEYWORD'] == kw]
                brand = brand_row['GROUP'].values[0] if not brand_row.empty else "기타"
                for p, r in trends.items():
                    results.append({"브랜드": brand, "기간": p, "키워드": kw, "검색량": int((r/total_r)*vol) if total_r>0 else 0})
            progress.progress(0.5 + (idx+1)/(len(final_kws)*2))
            time.sleep(0.05)
        
        status.empty(); progress.empty()

        if results:
            df = pd.DataFrame(results)
            df_grp = df.groupby(['기간', '브랜드'])['검색량'].sum().reset_index()
            df_grp['비중'] = (df_grp['검색량'] / df_grp.groupby('기간')['검색량'].transform('sum') * 100).round(1)
            
            fig = px.bar(df_grp, x="검색량", y="기간", color="브랜드", orientation='h', barmode='stack',
                         text=df_grp.apply(lambda x: f"{x['검색량']:,} ({x['비중']}%)", axis=1), height=600)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df.pivot_table(index=["브랜드", "키워드"], columns="기간", values="검색량", aggfunc="sum"))
else:
    st.info("분석할 키워드를 선택하거나 상단의 프리셋 버튼을 클릭해 주세요.")
