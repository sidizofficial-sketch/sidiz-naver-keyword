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
    
    # time_unit 매핑: 일간(date), 주간(week), 월간(month)
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
            # 주차별/월별/일자별 라벨 정리
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
st.set_page_config(page_title="의자 트렌드 분석기", layout="wide")

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

with st.sidebar:
    st.header("⚙️ 설정")
    sheet_id = st.text_input("Google Sheet ID", value="1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    st.markdown("---")
    st.subheader("📅 분석 기준 및 기간")
    time_unit = st.radio("분석 단위", ["일자별", "주차별", "월별"], index=2)
    s_date = st.date_input("시작일", datetime.now() - timedelta(days=60))
    e_date = st.date_input("종료일", datetime.now())

master_df = load_data_from_gsheets(sheet_id)
st.title(f"📊 {time_unit} 키워드 그룹 비중 대시보드")

# --- 비교 그룹 설정 ---
num_groups = st.slider("비교 그룹 수", 1, 5, 2)
cols = st.columns(num_groups)
filter_configs = {}

for i in range(num_groups):
    with cols[i]:
        with st.expander(f"비교 대상 {i+1}", expanded=True):
            label = st.text_input(f"대상 이름", f"그룹 {i+1}", key=f"l_{i}")
            grs = st.multiselect(f"브랜드", options=sorted(master_df['GROUP'].unique()), key=f"g_{i}")
            if grs:
                kws = sorted(master_df[master_df['GROUP'].isin(grs)]['KEYWORD'].unique())
                sel_all = st.checkbox("전체 선택", value=True, key=f"all_{i}")
                sel_kws = st.multiselect("키워드", options=kws, default=kws if sel_all else [], key=f"kw_{i}")
                filter_configs[label] = sel_kws

# --- 4. 분석 실행 섹션 ---
if st.button(f"📈 {time_unit} 데이터 분석 시작"):
    all_results = []
    with st.spinner(f"네이버 API에서 {time_unit} 데이터를 수집 중..."):
        for label, keywords in filter_configs.items():
            if not keywords: continue
            for kw in keywords:
                total_vol = get_naver_search_vol(kw, NAVER_KEYS["api"], NAVER_KEYS["sec"], NAVER_KEYS["cust"])
                trends = get_datalab_trend(kw, NAVER_KEYS["client_id"], NAVER_KEYS["client_secret"], s_date, e_date, time_unit)
                
                if trends:
                    total_ratio = sum(trends.values())
                    for period, ratio in trends.items():
                        # 선택한 단위(일/주/월)별로 검색량 배분
                        period_vol = int((ratio / total_ratio) * total_vol) if total_ratio > 0 else 0
                        all_results.append({
                            "비교대상": label, 
                            "기간": period, 
                            "키워드": kw, 
                            "검색량": period_vol
                        })

    if all_results:
        df_res = pd.DataFrame(all_results)
        
        # 데이터 통합
        df_group = df_res.groupby(['기간', '비교대상'])['검색량'].sum().reset_index()
        df_group['기간총합'] = df_group.groupby('기간')['검색량'].transform('sum')
        df_group['비중'] = (df_group['검색량'] / df_group['기간총합'] * 100).round(1)
        df_group['라벨'] = df_group.apply(lambda x: f"{x['검색량']:,} ({x['비중']}%)", axis=1)

        # 시각화 (Y축 라벨이 기간으로 변경됨)
        fig_main = px.bar(
            df_group, x="검색량", y="기간", color="비교대상", 
            orientation='h', text="라벨", barmode='stack',
            title=f"{time_unit} 통합 검색량 및 비중 비교",
            height=600 if time_unit != "일자별" else 1200, # 일자별일 경우 그래프 길게
            color_discrete_sequence=px.colors.qualitative.Pastel
        )

        df_total_period = df_group.groupby('기간')['검색량'].sum().reset_index()
        for i, row in df_total_period.iterrows():
            fig_main.add_annotation(
                x=row['검색량'], y=row['기간'],
                text=f"  합계: {row['검색량']:,}",
                showarrow=False, xanchor='left', font=dict(size=11)
            )

        fig_main.update_traces(textposition='inside')
        fig_main.update_yaxes(categoryorder='category descending')
        st.plotly_chart(fig_main, use_container_width=True)
        
        # 상세 데이터 테이블
        st.markdown("---")
        st.subheader(f"📋 {time_unit} 상세 데이터")
        df_detail = df_res.pivot_table(
            index=["비교대상", "키워드"], columns="기간", values="검색량", aggfunc="sum", fill_value=0
        ).reset_index()
        st.dataframe(df_detail, use_container_width=True)
    else:
        st.warning("데이터를 불러오지 못했습니다. 설정을 확인해주세요.")
