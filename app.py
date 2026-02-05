import streamlit as st
import pandas as pd
import time
import hashlib
import hmac
import base64
import requests
import plotly.express as px
from datetime import datetime, timedelta

# --- 1. 네이버 API 인증 및 호출 함수 ---
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

# --- 2. 구글 시트 데이터 로딩 ---
@st.cache_data
def load_main_data(sheet_id):
    # 첫 번째 탭 데이터
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    df = pd.read_csv(url)
    df.columns = [c.strip().upper() for c in df.columns]
    return df

@st.cache_data
def load_presets(sheet_id):
    # PRESETS 탭 데이터 (탭 이름을 더 정확히 찾기 위해 gid 대신 sheet name 사용)
    # csv export 시 sheet 파라미터가 가끔 작동하지 않으므로 gviz api 활용
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=PRESETS"
    try:
        pdf = pd.read_csv(url)
        if pdf.empty: return {}
        pdf.columns = [c.strip().upper() for c in pdf.columns]
        presets = {}
        for _, row in pdf.iterrows():
            name = str(row['NAME']).strip()
            items = [i.strip() for i in str(row['KEYWORDS']).split(',')]
            presets[name] = items
        return presets
    except Exception as e:
        return {"error": str(e)}

# --- 3. UI 및 기본 설정 ---
st.set_page_config(page_title="시디즈 마케팅 분석 대시보드", layout="wide")

try:
    NAVER_KEYS = {
        "api": st.secrets["NAVER_API_KEY"], "sec": st.secrets["NAVER_SECRET_KEY"],
        "cust": st.secrets["NAVER_CUSTOMER_ID"], "client_id": st.secrets["NAVER_CLIENT_ID"],
        "client_secret": st.secrets["NAVER_CLIENT_SECRET"]
    }
except:
    st.error("Secrets 설정을 확인해주세요 (네이버 API 키 필요).")
    st.stop()

with st.sidebar:
    st.header("⚙️ 분석 설정")
    sheet_id = st.text_input("Google Sheet ID", value="1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    st.markdown("---")
    time_unit = st.radio("집계 단위", ["일자별", "주차별", "월별"], index=2)
    s_date = st.date_input("시작일", datetime(2024, 12, 1))
    e_date = st.date_input("종료일", datetime(2025, 1, 31))
    if st.button("🔄 시트 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()

# 데이터 호출
master_df = load_main_data(sheet_id)
sheet_presets = load_presets(sheet_id)

# 세션 상태 초기화
if 'active_preset_name' not in st.session_state: st.session_state.active_preset_name = None
if 'active_preset_kws' not in st.session_state: st.session_state.active_preset_kws = []

st.title("💺 시디즈 vs 경쟁사 마켓쉐어 관제 센터")

# --- 4. 시트 기반 프리셋 버튼 UI ---
if "error" in sheet_presets:
    st.sidebar.warning(f"PRESETS 탭을 찾을 수 없습니다. (에러: {sheet_presets['error']})")
    st.info("💡 구글 시트에 'PRESETS'라는 이름의 탭이 있는지, NAME과 KEYWORDS 열이 있는지 확인해주세요.")
elif sheet_presets:
    st.subheader("⚡ 퀵 그룹 분석 프리셋")
    p_cols = st.columns(5)
    for i, (p_name, p_items) in enumerate(sheet_presets.items()):
        with p_cols[i % 5]:
            if st.button(p_name, key=f"pbtn_{i}", use_container_width=True):
                # 지능형 매칭: 그룹명 또는 키워드명에 포함된 모든 데이터 추출
                matched_data = master_df[
                    master_df['GROUP'].isin(p_items) | 
                    master_df['KEYWORD'].isin(p_items)
                ]
                if not matched_data.empty:
                    st.session_state.active_preset_name = p_name
                    st.session_state.active_preset_kws = matched_data['KEYWORD'].unique().tolist()
                    st.rerun() # 즉시 반영을 위해 리런
                else:
                    st.error(f"'{p_name}'의 키워드({p_items})가 메인 시트에 없습니다.")
else:
    st.info("상단에 표시할 프리셋이 없습니다. 구글 시트의 'PRESETS' 탭을 확인해주세요.")

# --- 5. 분석 실행 및 결과 시각화 ---
st.markdown("---")
if st.session_state.active_preset_name:
    st.success(f"✅ 선택됨: **{st.session_state.active_preset_name}** ({len(st.session_state.active_preset_kws)}개 키워드 합산)")
    
    if st.button("🚀 분석 시작", type="primary"):
        all_results = []
        progress_bar = st.progress(0)
        kws = st.session_state.active_preset_kws
        
        for idx, kw in enumerate(kws):
            vol = get_naver_search_vol(kw, NAVER_KEYS["api"], NAVER_KEYS["sec"], NAVER_KEYS["cust"])
            trends = get_datalab_trend(kw, NAVER_KEYS["client_id"], NAVER_KEYS["client_secret"], s_date, e_date, time_unit)
            
            if trends:
                total_ratio = sum(trends.values())
                for period, ratio in trends.items():
                    val = int((ratio / total_ratio) * vol) if total_ratio > 0 else 0
                    row = master_df[master_df['KEYWORD'] == kw]
                    brand_name = row['GROUP'].values[0] if not row.empty else "알 수 없음"
                    all_results.append({
                        "분석그룹": st.session_state.active_preset_name,
                        "기간": period,
                        "상세키워드": kw,
                        "브랜드": brand_name,
                        "검색량": val
                    })
            progress_bar.progress((idx + 1) / len(kws))

        if all_results:
            df_res = pd.DataFrame(all_results)
            df_chart = df_res.groupby(['기간', '브랜드'])['검색량'].sum().reset_index()
            df_chart['비중'] = (df_chart['검색량'] / df_chart.groupby('기간')['검색량'].transform('sum') * 100).round(1)
            
            fig = px.bar(
                df_chart, x="검색량", y="기간", color="브랜드", 
                orientation='h', barmode='stack',
                text=df_chart.apply(lambda x: f"{x['검색량']:,} ({x['비중']}%)", axis=1),
                title=f"[{time_unit}] 통합 점유율 분석", height=600
            )
            fig.update_yaxes(categoryorder='category descending')
            st.plotly_chart(fig, use_container_width=True)
            
            with st.expander("📝 상세 키워드별 내역"):
                st.dataframe(df_res.pivot_table(index=["브랜드", "상세키워드"], columns="기간", values="검색량", aggfunc="sum"))
else:
    st.write("상단의 프리셋 버튼을 클릭하면 분석이 시작됩니다.")
