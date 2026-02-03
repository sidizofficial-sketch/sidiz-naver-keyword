import streamlit as st
import pandas as pd
import time
import hashlib
import hmac
import base64
import requests
import plotly.express as px
from datetime import datetime

# --- 1. 네이버 API 인증 및 데이터 호출 함수 ---
def generate_signature(timestamp, method, uri, secret_key):
    message = f"{timestamp}.{method}.{uri}"
    hash = hmac.new(bytes(secret_key, "utf-8"), bytes(message, "utf-8"), hashlib.sha256)
    return base64.b64encode(hash.digest()).decode()

# 검색광고 API (최근 30일 검색량 합계용)
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

# 데이터랩 API (월별 트렌드 비중 계산용)
def get_datalab_trend(keyword, client_id, client_secret, start_date, end_date):
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret, "Content-Type": "application/json"}
    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "timeUnit": "month",
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}]
    }
    try:
        res = requests.post(url, headers=headers, json=body).json()
        if 'results' in res:
            data = res['results'][0]['data']
            return {d['period'][:7]: d['ratio'] for d in data} # {'2024-12': 100.0, ...}
    except: pass
    return {}

# --- 2. 데이터 로딩 ---
@st.cache_data
def load_data_from_gsheets(sheet_id):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    df = pd.read_csv(url)
    df.columns = [c.strip().upper() for c in df.columns]
    return df

# --- 3. UI 및 설정 ---
st.set_page_config(page_title="의자 월별 키워드 분석기", layout="wide")

# Secrets 설정 확인 (데이터랩 키 추가 필요)
try:
    NAVER_KEYS = {
        "api": st.secrets["NAVER_API_KEY"],
        "sec": st.secrets["NAVER_SECRET_KEY"],
        "cust": st.secrets["NAVER_CUSTOMER_ID"],
        "client_id": st.secrets.get("NAVER_CLIENT_ID", ""), # 데이터랩용
        "client_secret": st.secrets.get("NAVER_CLIENT_SECRET", "") # 데이터랩용
    }
except:
    st.error("Secrets 설정에 NAVER API 키들을 등록해주세요.")
    st.stop()

with st.sidebar:
    st.header("⚙️ 설정")
    sheet_id = st.text_input("Google Sheet ID", value="1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    st.markdown("---")
    st.subheader("📅 분석 기간 설정")
    s_date = st.date_input("시작일", datetime(2024, 12, 1))
    e_date = st.date_input("종료일", datetime(2025, 1, 31))

master_df = load_data_from_gsheets(sheet_id)
st.title("💺 월별 키워드 그룹 비중 대시보드")

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

# --- 분석 실행 ---
if st.button("📈 월별 데이터 분석 시작"):
    all_results = []
    with st.spinner("월별 트렌드를 계산 중입니다..."):
        for label, keywords in filter_configs.items():
            for kw in keywords:
                # 1. 광고 API로 최근 볼륨 획득
                total_vol = get_naver_search_vol(kw, NAVER_KEYS["api"], NAVER_KEYS["sec"], NAVER_KEYS["cust"])
                # 2. 데이터랩 API로 월별 비중 획득
                trends = get_datalab_trend(kw, NAVER_KEYS["client_id"], NAVER_KEYS["client_secret"], s_date, e_date)
                
                # 3. 비중에 맞춰 월별 검색량 배분
                if trends:
                    total_ratio = sum(trends.values())
                    for month, ratio in trends.items():
                        monthly_vol = int((ratio / total_ratio) * total_vol) if total_ratio > 0 else 0
                        all_results.append({"비교대상": label, "년월": month, "키워드": kw, "검색량": monthly_vol})

if all_results:
        df_res = pd.DataFrame(all_results)
        
        # 1. 시각화를 위해 데이터 그룹화 (년월, 비교대상별로 합산)
        # 키워드별로 너무 잘게 쪼개지면 비중 비교가 어려우므로 그룹 단위로 합칩니다.
        df_monthly_group = df_res.groupby(["년월", "비교대상"])["검색량"].sum().reset_index()

        # 2. 그래프 생성
        # Y축은 '년월', X축은 '검색량', 색상은 '비교대상(그룹1, 2)'
        fig_main = px.bar(
            df_monthly_group, 
            x="검색량", 
            y="년월", 
            color="비교대상", 
            orientation='h', 
            title="월별 그룹 통합 검색량 비중 비교",
            text_auto='.2s', 
            height=500,
            barmode='stack', # 그룹1과 그룹2가 한 막대에 쌓임
            color_discrete_sequence=px.colors.qualitative.Pastel # 부드러운 색상 적용
        )

        # 3. Y축 정렬 및 레이아웃 설정 (AttributeError 방지 위해 fig_main 사용)
        fig_main.update_yaxes(categoryorder='category descending')
        fig_main.update_layout(
            legend_title="비교 그룹",
            xaxis_title="총 검색량 합계",
            yaxis_title="조회 월 (Month)",
            margin=dict(l=20, r=20, t=50, b=20)
        )

        st.plotly_chart(fig_main, use_container_width=True)
        
        # --- 4. 하단 상세 테이블 (요청하신 월 단위 설정) ---
        st.markdown("---")
        st.subheader("📋 월별/키워드별 상세 검색량")
        
        # 데이터를 보기 좋게 피벗 (행: 키워드, 열: 년월)
        df_detail = df_res.pivot_table(
            index=["비교대상", "키워드"], 
            columns="년월", 
            values="검색량", 
            aggfunc="sum",
            fill_value=0
        ).reset_index()
        
        st.dataframe(df_detail, use_container_width=True)

   else:
        st.warning("조회된 데이터가 없습니다. 키워드 선택이나 API 설정을 확인해주세요.")
