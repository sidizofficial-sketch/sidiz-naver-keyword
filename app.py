import streamlit as st
import pandas as pd
import time
import hashlib
import hmac
import base64
import requests
import plotly.express as px
from datetime import datetime

# --- 1. 네이버 API 인증 및 호출 함수 (안정성 강화) ---
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
        # 타임아웃을 10초로 늘려 안정성 확보
        res = requests.get(BASE_URL + uri, params=params, headers=headers, timeout=10).json()
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
        res = requests.post(url, headers=headers, json=body, timeout=10).json()
        if 'results' in res and res['results'][0]['data']:
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
st.set_page_config(page_title="시디즈 마케팅 대시보드", layout="wide")

try:
    keys = {k: st.secrets[k.upper()] for k in ["naver_api_key", "naver_secret_key", "naver_customer_id", "naver_client_id", "naver_client_secret"]}
except:
    st.error("Secrets 설정 오류"); st.stop()

with st.sidebar:
    st.header("⚙️ 기본 설정")
    sid = st.text_input("Sheet ID", "1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    unit = st.radio("집계 단위", ["일자별", "주차별", "월별"], index=2)
    s_date = st.date_input("시작일", datetime(2024, 12, 1))
    e_date = st.date_input("종료일", datetime(2025, 1, 31))
    if st.button("🔄 전체 새로고침"): st.cache_data.clear(); st.rerun()

master_df, presets = load_all_data(sid)

# 세션 상태 관리
if 'active_groups' not in st.session_state: st.session_state.active_groups = {}
if 'num_targets' not in st.session_state: st.session_state.num_targets = 2

st.title("📊 시리즈별 마켓쉐어 상세 분석")

# --- 4. 프리셋 버튼 ---
if presets:
    st.subheader("⚡ 퀵 프리셋")
    p_cols = st.columns(len(presets) if len(presets) < 6 else 5)
    for i, (name, items) in enumerate(presets.items()):
        with p_cols[i % 5]:
            if st.button(name, key=f"p_{i}", use_container_width=True):
                matched = master_df[master_df['GROUP'].isin(items) | master_df['KEYWORD'].isin(items)]
                st.session_state.num_targets = 1
                st.session_state.active_groups = {
                    "label_0": name,
                    "groups_0": matched['GROUP'].unique().tolist(),
                    "kws_0": matched['KEYWORD'].unique().tolist()
                }
                st.rerun()

st.markdown("---")

# --- 5. 분석 대상 설정 ---
st.subheader("🛠️ 분석 대상 설정")
num_targets = st.number_input("분석 대상 개수", min_value=1, max_value=5, value=st.session_state.num_targets)
st.session_state.num_targets = num_targets

final_filter = {}
group_options = sorted(master_df['GROUP'].unique().tolist())
cols = st.columns(num_targets)

for i in range(num_targets):
    with cols[i]:
        def_label = st.session_state.active_groups.get(f"label_{i}", f"비교군 {i+1}")
        def_groups = st.session_state.active_groups.get(f"groups_{i}", [])
        def_kws = st.session_state.active_groups.get(f"kws_{i}", [])

        label = st.text_input(f"대상 {i+1} 이름", value=def_label, key=f"lab_{i}")
        sel_groups = st.multiselect(f"그룹(브랜드) 선택", options=group_options, default=def_groups, key=f"gr_{i}")
        
        if sel_groups:
            kw_options = sorted(master_df[master_df['GROUP'].isin(sel_groups)]['KEYWORD'].unique().tolist())
            current_def = [k for k in def_kws if k in kw_options] if def_kws else kw_options
            sel_kws = st.multiselect(f"키워드 선택", options=kw_options, default=current_def, key=f"kw_{i}")
            if label and sel_kws:
                final_filter[label] = sel_kws

# --- 6. 분석 실행 (강력한 예외처리 버전) ---
st.markdown("---")
if final_filter:
    if st.button("🚀 분석 시작", type="primary", use_container_width=True):
        results = []
        all_unique_kws = list(set([kw for kws in final_filter.values() for kw in kws]))
        
        progress = st.progress(0)
        status = st.empty()
        
        # 1단계: 검색량 조회
        all_vols = {}
        for i in range(0, len(all_unique_kws), 5):
            chunk = all_unique_kws[i:i+5]
            status.text(f"🔍 네이버 검색량 데이터 수집 중... ({min(i+5, len(all_unique_kws))}/{len(all_unique_kws)})")
            all_vols.update(get_naver_search_vols_bulk(chunk, keys["naver_api_key"], keys["naver_secret_key"], keys["naver_customer_id"]))
            progress.progress(min((i+5)/(len(all_unique_kws)*2), 0.4))
            time.sleep(0.2) # 속도 조절

        # 2단계: 트렌드 조회 및 매칭
        current_idx = 0
        total_kws = sum(len(v) for v in final_filter.values())
        
        for group_label, kws in final_filter.items():
            for kw in kws:
                current_idx += 1
                status.text(f"⏳ [{group_label}] 분석 중: {kw} ({current_idx}/{total_kws})")
                
                vol = all_vols.get(kw, 0)
                trends = get_datalab_trend(kw, keys["naver_client_id"], keys["naver_client_secret"], s_date, e_date, unit)
                
                if trends:
                    total_r = sum(trends.values())
                    for p, r in trends.items():
                        results.append({
                            "분석대상": group_label, "기간": p, "키워드": kw,
                            "검색량": int((r/total_r)*vol) if total_r > 0 else 0
                        })
                progress.progress(0.4 + (current_idx / total_kws / 1.7))
                time.sleep(0.1)

        status.empty(); progress.empty()

        if results:
            df = pd.DataFrame(results)
            df_grp = df.groupby(['기간', '분석대상'])['검색량'].sum().reset_index()
            df_grp['비중'] = (df_grp['검색량'] / df_grp.groupby('기간')['검색량'].transform('sum') * 100).round(1)
            
            fig = px.bar(df_grp, x="검색량", y="기간", color="분석대상", orientation='h', barmode='stack',
                         text=df_grp.apply(lambda x: f"{x['검색량']:,} ({x['비중']}%)", axis=1), height=600,
                         color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df.pivot_table(index=["분석대상", "키워드"], columns="기간", values="검색량", aggfunc="sum"))
        else:
            st.error("데이터를 수집하지 못했습니다. 키워드 선택을 줄이거나 API 설정을 확인하세요.")
