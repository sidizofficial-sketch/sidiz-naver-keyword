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
        
        # 💡 핵심 수정: '비교대상'과 '키워드'를 합쳐서 범례(Color)에 표시합니다.
        # 이렇게 하면 Y축은 '년월' 하나로 통합되고, 막대 안에서 그룹별 비중이 보입니다.
        df_res["구분"] = df_res["비교대상"] + ": " + df_res["키워드"]

        # 그래프 생성
        fig = px.bar(
            df_res, 
            x="검색량", 
            y="년월", 
            color="구분",              # 그룹명과 키워드가 같이 표시됨
            orientation='h', 
            title="월별 그룹 통합 키워드 비중 비교",
            text_auto='.2s', 
            height=600,               # 높이는 고정해서 보기 편하게 조정
            barmode='stack'           # 누적 막대 형식
        )

        # Y축 내림차순 정렬 (최신달이 위로 오게)
        fig.update_yaxis(categoryorder='category descending')
        
        # 레이아웃 깔끔하게 정리
        fig.update_layout(
            legend_title="그룹별 키워드",
            xaxis_title="총 검색량 합계",
            yaxis_title="조회 월"
        )

        st.plotly_chart(fig, use_container_width=True)
        
        # 하단 데이터 테이블 (년월별로 그룹화해서 보기)
        st.subheader("📋 월별 상세 수치")
        pivot_df = df_res.pivot_table(
            index=["년월", "비교대상"], 
            values="검색량", 
            aggfunc="sum"
        ).reset_index()
        st.dataframe(pivot_df)
        
        # 하단 상세 테이블
        st.subheader("📋 월별 상세 검색량 데이터")
        st.dataframe(df_res.sort_values(["비교대상", "년월", "검색량"], ascending=[True, True, False]))
