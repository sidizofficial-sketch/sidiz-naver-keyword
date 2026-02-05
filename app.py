import streamlit as st
import pandas as pd
import time
import hashlib
import hmac
import base64
import requests
import plotly.express as px
from datetime import datetime

# --- 1. 네이버 API 호출 (에러 메시지 출력 강화) ---
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
        res = requests.get(BASE_URL + uri, params=params, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if 'keywordList' in data:
                for item in data['keywordList']:
                    pc = str(item['monthlyPcQcCnt']).replace('< ', '10')
                    mo = str(item['monthlyMobileQcCnt']).replace('< ', '10')
                    vols[item['relKeyword']] = int(pc) + int(mo)
        else:
            st.error(f"⚠️ 광고 API 연결 실패 (코드: {res.status_code})")
    except Exception as e:
        st.error(f"⚠️ 광고 API 오류: {str(e)}")
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
        res = requests.post(url, headers=headers, json=body, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if 'results' in data and data['results'][0]['data']:
                return {d['period']: d['ratio'] for d in data['results'][0]['data']}
        elif res.status_code == 429:
            st.warning(f"🚨 데이터랩 API 일일 한도가 초과되었습니다.")
        else:
            st.error(f"⚠️ 데이터랩 API 실패 (코드: {res.status_code})")
    except Exception as e:
        st.error(f"⚠️ 데이터랩 API 오류: {str(e)}")
    return {}

# --- 2. 데이터 로딩 ---
@st.cache_data(ttl=600)
def load_all_data(sheet_id):
    main_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    m_df = pd.read_csv(main_url)
    m_df.columns = [c.strip().upper() for c in m_df.columns]
    return m_df

# --- 3. UI 및 설정 ---
st.set_page_config(page_title="시디즈 마켓쉐어 분석 진단", layout="wide")

try:
    keys = {k: st.secrets[k.upper()] for k in ["naver_api_key", "naver_secret_key", "naver_customer_id", "naver_client_id", "naver_client_secret"]}
except:
    st.error("Secrets 설정(API 키)을 확인할 수 없습니다."); st.stop()

with st.sidebar:
    st.header("⚙️ 분석 설정")
    sid = st.text_input("Sheet ID", "1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    unit = st.radio("집계 단위", ["일자별", "주차별", "월별"], index=2)
    s_date = st.date_input("시작일", datetime(2024, 12, 1))
    e_date = st.date_input("종료일", datetime(2025, 1, 31))
    st.markdown("---")
    use_dummy = st.checkbox("🆘 API 실패 시 가짜 데이터로 그래프 테스트")

master_df = load_all_data(sid)

# 세션 상태 초기화
if 'targets' not in st.session_state: st.session_state.targets = 2

st.title("📊 마켓쉐어 분석 진단 모드")

# --- 4. 분석 대상 설정 ---
group_options = sorted(master_df['GROUP'].unique().tolist())
cols = st.columns(st.session_state.targets)
final_filter = {}

for i in range(st.session_state.targets):
    with cols[i]:
        label = st.text_input(f"분석 대상 {i+1} 이름", value=f"비교군 {i+1}", key=f"lab_{i}")
        sel_groups = st.multiselect(f"그룹(브랜드) 선택", options=group_options, key=f"gr_{i}")
        if sel_groups:
            kw_options = sorted(master_df[master_df['GROUP'].isin(sel_groups)]['KEYWORD'].unique().tolist())
            sel_kws = st.multiselect(f"키워드 선택", options=kw_options, key=f"kw_{i}")
            if label and sel_kws:
                final_filter[label] = sel_kws

# --- 5. 분석 및 결과 ---
if final_filter:
    if st.button("🚀 분석 시작", type="primary", use_container_width=True):
        results = []
        all_unique_kws = list(set([kw for kws in final_filter.values() for kw in kws]))
        
        status = st.empty()
        # 1단계: 검색량 조회
        status.info("🔍 네이버 검색량 데이터 수집 중...")
        all_vols = get_naver_search_vols_bulk(all_unique_kws, keys["naver_api_key"], keys["naver_secret_key"], keys["naver_customer_id"])
        
        # 2단계: 트렌드 조회
        for g_label, kws in final_filter.items():
            for kw in kws:
                status.info(f"⏳ [{g_label}] 분석 중: {kw}")
                vol = all_vols.get(kw, 1000 if use_dummy else 0) # 더미모드 시 1000 부여
                trends = get_datalab_trend(kw, keys["naver_client_id"], keys["naver_client_secret"], s_date, e_date, unit)
                
                if not trends and use_dummy: # 더미모드 활성화 시 가짜 데이터 생성
                    trends = { (s_date + timedelta(days=x)).strftime("%Y-%m-%d"): (x+1)*10 for x in range(5) }
                
                if trends:
                    total_r = sum(trends.values())
                    for p, r in trends.items():
                        results.append({
                            "분석대상": g_label, "기간": p, "키워드": kw,
                            "검색량": int((r/total_r)*vol) if total_r > 0 else 0
                        })
        status.empty()

        if results:
            df = pd.DataFrame(results)
            df_grp = df.groupby(['기간', '분석대상'])['검색량'].sum().reset_index()
            fig = px.bar(df_grp, x="검색량", y="기간", color="분석대상", orientation='h', barmode='stack', text_auto=',.0f')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error("데이터 수집에 실패했습니다. 사이드바의 '가짜 데이터 테스트'를 켜서 UI가 정상인지 확인해보세요.")
