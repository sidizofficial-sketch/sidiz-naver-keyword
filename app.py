import streamlit as st
import pandas as pd
import time
import hashlib
import hmac
import base64
import requests
import plotly.express as px

# --- 1. 네이버 API 인증 설정 ---
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
    
    headers = {
        'Content-Type': 'application/json; charset=UTF-8',
        'X-Timestamp': timestamp,
        'X-API-KEY': api_key,
        'X-Customer': customer_id,
        'X-Signature': signature
    }
    params = {'hintKeywords': keyword, 'showDetail': '1'}
    
    try:
        response = requests.get(BASE_URL + uri, params=params, headers=headers)
        data = response.json()
        if 'keywordList' in data and len(data['keywordList']) > 0:
            target = data['keywordList'][0]
            pc_val = str(target['monthlyPcQcCnt']).replace('< ', '')
            mo_val = str(target['monthlyMobileQcCnt']).replace('< ', '')
            return {
                "pc": int(pc_val) if pc_val.isdigit() else 10,
                "mobile": int(mo_val) if mo_val.isdigit() else 10
            }
    except:
        pass
    return {"pc": 0, "mobile": 0}

# --- 2. 데이터 로딩 (구글 시트) ---
@st.cache_data
def load_data_from_gsheets(sheet_id):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    return pd.read_csv(url)

# --- 3. UI 구성 및 Secrets 적용 ---
st.set_page_config(page_title="의자 키워드 비교 분석기", layout="wide")

# Secrets에서 키값 불러오기 (매번 입력할 필요 없음)
try:
    api_key = st.secrets["NAVER_API_KEY"]
    secret_key = st.secrets["NAVER_SECRET_KEY"]
    customer_id = st.secrets["NAVER_CUSTOMER_ID"]
except KeyError:
    st.error("Streamlit Secrets 설정이 필요합니다. NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID를 설정해주세요.")
    st.stop()

with st.sidebar:
    st.header("⚙️ 데이터 설정")
    sheet_id = st.text_input("Google Sheet ID", value="1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    
    # 📅 기간 설정 추가
    st.markdown("---")
    st.subheader("📅 분석 기간 설정")
    start_date = st.date_input("시작일", pd.to_datetime("2025-01-01"))
    end_date = st.date_input("종료일", pd.to_datetime("today"))

# 시트 데이터 불러오기
try:
    master_df = load_data_from_gsheets(sheet_id)
except:
    st.error("구글 시트를 불러올 수 없습니다. 시트 ID와 공유 설정을 확인해주세요.")
    st.stop()

st.title("💺 의자 키워드 그룹별 비교 대시보드")

# --- 비교 필터 섹션 (여러 개 선택 가능하도록 최적화) ---
st.subheader("🛠️ 비교 그룹 설정 (최대 10개)")
num_groups = st.slider("비교할 그룹 개수", 1, 10, 2)

cols = st.columns(min(num_groups, 3)) 
filter_configs = {}

for i in range(num_groups):
    with cols[i % 3]:
        with st.expander(f"비교 대상 {i+1}", expanded=True):
            group_label = st.text_input(f"그룹 이름 {i+1}", f"대상 {i+1}", key=f"label_{i}")
            
            # 1. 여러 그룹(브랜드) 선택 가능
            all_groups = sorted(master_df['GROUP'].unique().tolist())
            selected_groups = st.multiselect(
                f"포함할 그룹(GROUP) - 여러 개 선택 가능", 
                options=all_groups, 
                key=f"gr_{i}",
                help="드롭다운에서 여러 브랜드를 클릭하여 추가하세요."
            )
            
            # 2. 선택된 그룹들에 속한 모든 키워드 자동 나열
            if selected_groups:
                available_kws = master_df[master_df['GROUP'].isin(selected_groups)]['KEYWORD'].unique().tolist()
                
                # 키워드도 여러 개 선택 가능 (기본값으로 해당 그룹의 모든 키워드 설정)
                selected_kws = st.multiselect(
                    f"세부 키워드 선택", 
                    options=sorted(available_kws), 
                    default=available_kws, 
                    key=f"kw_{i}"
                )
                filter_configs[group_label] = selected_kws
            else:
                st.info("먼저 그룹(브랜드)을 선택해주세요.")
# --- 분석 실행 ---
if st.button("📈 데이터 분석 및 차트 생성"):
    all_plot_data = []
    with st.spinner("네이버 API에서 실시간 데이터를 조회 중입니다..."):
        progress_bar = st.progress(0)
        for idx, (label, kws) in enumerate(filter_configs.items()):
            if not kws: continue
            for kw in kws:
                vol_data = get_naver_search_vol(kw, api_key, secret_key, customer_id)
                all_plot_data.append({"비교대상": label, "키워드": kw, "검색량": vol_data["pc"] + vol_data["mobile"]})
            progress_bar.progress((idx + 1) / len(filter_configs))

    if all_plot_data:
        res_df = pd.DataFrame(all_plot_data)
        fig = px.bar(res_df, x="검색량", y="비교대상", color="키워드", orientation='h', title="그룹별 키워드 비중 비교", text_auto='.2s', color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_layout(barmode='stack', yaxis={'categoryorder':'total ascending'})
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(res_df)
    else:
        st.error("선택된 키워드가 없습니다.")
