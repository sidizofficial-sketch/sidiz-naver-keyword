import streamlit as st
import pandas as pd
import time
import hashlib
import hmac
import base64
import requests
import plotly.express as px
from datetime import datetime, timedelta

# --- 1. 네이버 API 인증 및 데이터 호출 함수 ---
def generate_signature(timestamp, method, uri, secret_key):
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(bytes(secret_key, "utf-8"), bytes(message, "utf-8"), hashlib.sha256)
    return base64.b64encode(hash.digest()).decode()

def get_naver_search_vol(keyword, api_key, secret_key, customer_id):
    BASE_URL = 'https://api.searchad.naver.com'
    uri = '/keywordstool'
    method = 'GET'
    timestamp = str(round(time.time() * 1000))
    signature = generate_signature(timestamp, method, uri, secret_key)
    headers = {'X-Timestamp': timestamp, 'X-API-KEY': api_key, 'X-Customer': customer_id, 'X-Signature': signature}
    params = {'hintKeywords': keyword, 'showDetail': '1'}
    try:
        res = requests.get(BASE_URL + uri, params=params, headers=headers).json()
        if 'keywordList' in res:
            target = res['keywordList'][0]
            pc = str(target['monthlyPcQcCnt']).replace('< ', '10')
            mo = str(target['monthlyMobileQcCnt']).replace('< ', '10')
            return int(pc) + int(mo)
    except: pass
    return 0

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
            data = res['results'][0]['data']
            return {d['period']: d['ratio'] for d in data}
    except: pass
    return {}

# --- 2. 데이터 로딩 ---
@st.cache_data
def load_data_from_gsheets(sheet_id):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    df = pd.read_csv(url)
    df.columns = [c.strip().upper() for c in df.columns]
    return df

# --- 3. UI 설정 ---
st.set_page_config(page_title="시디즈 마케팅 분석기", layout="wide")

try:
    NAVER_KEYS = {
        "api": st.secrets["NAVER_API_KEY"],
        "sec": st.secrets["NAVER_SECRET_KEY"],
        "cust": st.secrets["NAVER_CUSTOMER_ID"],
        "client_id": st.secrets["NAVER_CLIENT_ID"],
        "client_secret": st.secrets["NAVER_CLIENT_SECRET"]
    }
except:
    st.error("Secrets 설정을 확인해주세요.")
    st.stop()

# 프리셋 정의 (요청하신 10개 그룹)
PRESETS = {
    "1. GC PRO & GX": ["제닉스", "시크릿랩", "클라우드백", "GC PRO", "GX", "에이픽스", "듀오백"],
    "2. T80 & T90": ["허먼밀러", "에어론", "T80", "스틸케이스", "T90", "휴먼스케일", "엠바디", "하워스"],
    "3. T50 & T60": ["T50", "T60", "듀오백 브라보", "에르고휴먼", "리바트 테크닉", "사이즈오브체어"],
    "4. T20": ["T20", "오토노스", "딥워크", "에르먼", "이케아 마르쿠스", "듀오백 Q1", "이케아 맛크스펠", "리바트 어센트"],
    "5. RINGO": ["RINGO", "니스툴그로우", "파트라 제미니", "루나랩키즈", "듀오백 밀키", "듀오백 래빗", "라베스토", "체어스코 아토"],
    "6. IBLE": ["IBLE", "사오체 몰입체어", "듀오백 서울대의자", "루게"],
    "7. TREVO": ["TREVO", "이케아 우르반", "피노키오", "비카", "이케아 이감", "리틀피노", "세븐 체어"],
    "8. ATTI": ["ATTI", "리바트 꼼므", "펀펀키즈", "야마토야 부오노", "프렌디아"],
    "9. MOLTI": ["스토케 트립트랩", "싸이벡스 레모", "본베베", "MOLTI"],
    "10. EGA & BUTTON & LINIE": ["EGA", "MANE", "이케아 알레피엘", "이케아 하테피엘", "무인양품", "이케아 롱피엘", "BUTTON", "이케아 밀베리에트"]
}

with st.sidebar:
    st.header("⚙️ 설정")
    sheet_id = st.text_input("Google Sheet ID", value="1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    st.markdown("---")
    st.subheader("📅 분석 기준 및 기간")
    time_unit = st.radio("분석 단위", ["일자별", "주차별", "월별"], index=2)
    s_date = st.date_input("시작일", datetime(2024, 12, 1))
    e_date = st.date_input("종료일", datetime(2025, 1, 31))

master_df = load_data_from_gsheets(sheet_id)
st.title("💺 시디즈 vs 경쟁사 시리즈별 분석 대시보드")

# --- 4. 빠른 비교 프리셋 버튼 ---
st.subheader("⚡ 빠른 비교 프리셋")
preset_cols = st.columns(5)
selected_preset_kws = []

for i, (name, keywords) in enumerate(PRESETS.items()):
    with preset_cols[i % 5]:
        if st.button(name, use_container_width=True):
            # 시트 데이터에서 해당 키워드가 포함된 행 필터링
            selected_preset_kws = master_df[master_df['KEYWORD'].str.contains('|'.join(keywords), na=False, case=False)]['KEYWORD'].tolist()
            st.success(f"'{name}' 그룹이 선택되었습니다.")

# --- 5. 비교 그룹 설정 UI ---
st.markdown("---")
num_groups = st.slider("비교 그룹 수 (직접 설정 시)", 1, 5, 2)
cols = st.columns(num_groups)
filter_configs = {}

for i in range(num_groups):
    with cols[i]:
        with st.expander(f"비교 대상 {i+1}", expanded=True):
            label = st.text_input(f"대상 이름", f"그룹 {i+1}", key=f"l_{i}")
            grs = st.multiselect(f"브랜드(GROUP)", options=sorted(master_df['GROUP'].unique()), key=f"g_{i}")
            if grs:
                kws_options = sorted(master_df[master_df['GROUP'].isin(grs)]['KEYWORD'].unique())
                # 프리셋 버튼이 눌렸다면 해당 키워드를 기본값으로 세팅
                default_kws = [k for k in kws_options if k in selected_preset_kws] if selected_preset_kws else kws_options
                
                sel_kws = st.multiselect("키워드", options=kws_options, default=default_kws, key=f"kw_{i}")
                filter_configs[label] = sel_kws

# --- 6. 분석 실행 ---
if st.button(f"📈 {time_unit} 데이터 분석 시작"):
    all_results = []
    with st.spinner(f"네이버 API 데이터 수집 중..."):
        for label, keywords in filter_configs.items():
            if not keywords: continue
            for kw in keywords:
                total_vol = get_naver_search_vol(kw, NAVER_KEYS["api"], NAVER_KEYS["sec"], NAVER_KEYS["cust"])
                trends = get_datalab_trend(kw, NAVER_KEYS["client_id"], NAVER_KEYS["client_secret"], s_date, e_date, time_unit)
                
                if trends:
                    total_ratio = sum(trends.values())
                    for period, ratio in trends.items():
                        period_vol = int((ratio / total_ratio) * total_vol) if total_ratio > 0 else 0
                        all_results.append({"비교대상": label, "기간": period, "키워드": kw, "검색량": period_vol})

    if all_results:
        df_res = pd.DataFrame(all_results)
        df_group = df_res.groupby(['기간', '비교대상'])['검색량'].sum().reset_index()
        df_group['비중'] = (df_group['검색량'] / df_group.groupby('기간')['검색량'].transform('sum') * 100).round(1)
        
        fig = px.bar(df_group, x="검색량", y="기간", color="비교대상", orientation='h', text=df_group.apply(lambda x: f"{x['검색량']:,} ({x['비중']}%)", axis=1),
                     barmode='stack', title=f"[{time_unit}] 시리즈별 시장 점유율 분석", height=600, color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_yaxes(categoryorder='category descending')
        st.plotly_chart(fig, use_container_width=True)
        
        st.subheader("📋 상세 수치 데이터")
        st.dataframe(df_res.pivot_table(index=["비교대상", "키워드"], columns="기간", values="검색량", aggfunc="sum", fill_value=0), use_container_width=True)
