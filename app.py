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

# --- 4. 분석 실행 섹션 ---

# 변수 초기화 (에러 방지용)
all_results = []

if st.button("📈 월별 데이터 분석 시작"):
    with st.spinner("네이버 API에서 데이터를 가져오는 중..."):
        # filter_configs에 설정된 그룹별로 루프
        for label, keywords in filter_configs.items():
            if not keywords: continue
            
            for kw in keywords:
                # 1. 검색광고 API: 전체 볼륨
                total_vol = get_naver_search_vol(kw, NAVER_KEYS["api"], NAVER_KEYS["sec"], NAVER_KEYS["cust"])
                
                # 2. 데이터랩 API: 월별 트렌드 (s_date, e_date 사용)
                trends = get_datalab_trend(kw, NAVER_KEYS["client_id"], NAVER_KEYS["client_secret"], s_date, e_date)
                
                # 3. 비중 계산 및 데이터 저장
                if trends:
                    total_ratio = sum(trends.values())
                    for month, ratio in trends.items():
                        # 트렌드 비중에 맞춰 전체 검색량을 월별로 배분
                        monthly_vol = int((ratio / total_ratio) * total_vol) if total_ratio > 0 else 0
                        all_results.append({
                            "비교대상": label, 
                            "년월": month, 
                            "키워드": kw, 
                            "검색량": monthly_vol
                        })
                else:
                    # 트렌드 데이터가 없을 경우 0으로 처리하거나 생략
                    pass

# 결과 출력
    if all_results:
        df_res = pd.DataFrame(all_results)
        
        # 1. 데이터를 '그룹(비교대상)' 단위로 먼저 통합 (키워드별 겹침 방지)
        df_group = df_res.groupby(['년월', '비교대상'])['검색량'].sum().reset_index()
        
        # 2. 그룹별 비중 계산
        df_group['월별총합'] = df_group.groupby('년월')['검색량'].transform('sum')
        df_group['비중'] = (df_group['검색량'] / df_group['월별총합'] * 100).round(1)
        
        # 막대 내부에 표시할 텍스트 (그룹 합계 + 그룹 비중)
        df_group['라벨'] = df_group.apply(lambda x: f"{x['검색량']:,} ({x['비중']}%)", axis=1)

        # 3. 시각화 설정
        fig_main = px.bar(
            df_group, 
            x="검색량", 
            y="년월", 
            color="비교대상", 
            orientation='h',
            title="월별 그룹 통합 검색량 및 비중 비교",
            text="라벨",             # 이제 그룹 단위 라벨이 들어갑니다
            height=500,
            barmode='stack',        # 그룹 1과 그룹 2가 나란히 쌓임
            color_discrete_sequence=px.colors.qualitative.Pastel
        )

        # 4. 막대 가장 끝(바깥쪽)에 총합계 표시
        # 월별로 모든 그룹의 합계를 계산하여 가장 오른쪽에 한 번만 표시
        df_total_month = df_group.groupby('년월')['검색량'].sum().reset_index()
        
        for i, row in df_total_month.iterrows():
            fig_main.add_annotation(
                x=row['검색량'], 
                y=row['년월'],
                text=f"  전체합계: {row['검색량']:,}", 
                showarrow=False,
                xanchor='left',      # 텍스트를 막대 오른쪽에 고정
                font=dict(size=13, color="black", family="Arial Black"),
                bgcolor="rgba(255, 255, 255, 0.7)" # 읽기 편하게 살짝 배경 추가
            )

        # 5. 그래프 디테일 조정
        fig_main.update_traces(
            textposition='inside',   # 그룹 라벨은 막대 안쪽에
            texttemplate='%{text}'
        )
        fig_main.update_yaxes(categoryorder='category descending')
        fig_main.update_layout(
            legend_title="비교 그룹",
            xaxis_title="검색량 합계",
            margin=dict(r=150),      # 오른쪽에 합계 텍스트 공간 충분히 확보
            uniformtext_minsize=10,
            uniformtext_mode='hide'
        )

        st.plotly_chart(fig_main, use_container_width=True)
        
        # 6. 상세 데이터 테이블 (키워드별 상세 수치는 표에서 확인)
        st.markdown("---")
        st.subheader("📋 키워드별 상세 검색량 데이터")
        df_detail = df_res.pivot_table(
            index=["비교대상", "키워드"], 
            columns="년월", 
            values="검색량", 
            aggfunc="sum", 
            fill_value=0
        ).reset_index()
        
        st.dataframe(df_detail, use_container_width=True)
