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
    headers = {
        'X-Timestamp': timestamp, 
        'X-API-KEY': api_key, 
        'X-Customer': customer_id, 
        'X-Signature': signature
    }
    params = {
        'hintKeywords': ",".join(keywords[:5]), 
        'showDetail': '1'
    }
    vols = {}
    try:
        res = requests.get(BASE_URL + uri, params=params, headers=headers, timeout=10)
        res.raise_for_status()  # HTTP 오류 확인
        data = res.json()
        
        if 'keywordList' in data:
            for item in data['keywordList']:
                pc = str(item.get('monthlyPcQcCnt', '0')).replace('< ', '')
                mo = str(item.get('monthlyMobileQcCnt', '0')).replace('< ', '')
                try:
                    total = int(pc) + int(mo)
                except ValueError:
                    total = 0
                vols[item['relKeyword']] = total
    except requests.exceptions.RequestException as e:
        st.warning(f"검색량 API 오류: {str(e)}")
    except Exception as e:
        st.warning(f"데이터 처리 오류: {str(e)}")
    
    return vols

def get_datalab_trend(keyword, client_id, client_secret, start_date, end_date, time_unit):
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id": client_id, 
        "X-Naver-Client-Secret": client_secret, 
        "Content-Type": "application/json"
    }
    unit_map = {"일자별": "date", "주차별": "week", "월별": "month"}
    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "timeUnit": unit_map.get(time_unit, "month"),
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}]
    }
    try:
        res = requests.post(url, headers=headers, json=body, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        if 'results' in data and len(data['results']) > 0 and 'data' in data['results'][0]:
            return {d['period']: d['ratio'] for d in data['results'][0]['data']}
    except requests.exceptions.RequestException as e:
        st.warning(f"트렌드 API 오류 ({keyword}): {str(e)}")
    except Exception as e:
        st.warning(f"트렌드 처리 오류 ({keyword}): {str(e)}")
    
    return {}

# --- 2. 데이터 로딩 ---
@st.cache_data(ttl=600)
def load_all_data(sheet_id):
    try:
        main_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        m_df = pd.read_csv(main_url)
        m_df.columns = [c.strip().upper() for c in m_df.columns]
        
        # 필수 컬럼 확인
        if 'GROUP' not in m_df.columns or 'KEYWORD' not in m_df.columns:
            st.error(f"스프레드시트에 'GROUP', 'KEYWORD' 컬럼이 필요합니다. 현재 컬럼: {m_df.columns.tolist()}")
            return pd.DataFrame(), {}
        
    except Exception as e:
        st.error(f"메인 시트 로딩 실패: {str(e)}")
        return pd.DataFrame(), {}
    
    # 프리셋 로딩
    presets = {}
    try:
        preset_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=PRESETS"
        p_df = pd.read_csv(preset_url)
        p_df.columns = [c.strip().upper() for c in p_df.columns]
        
        name_col = next((c for c in p_df.columns if 'NAME' in c), None)
        kw_col = next((c for c in p_df.columns if 'KEYWORD' in c), None)
        
        if name_col and kw_col:
            for _, row in p_df.iterrows():
                name = str(row[name_col]).strip()
                keywords = str(row[kw_col]).strip()
                if name and keywords and name != 'nan' and keywords != 'nan':
                    presets[name] = [k.strip() for k in keywords.split(',') if k.strip()]
    except Exception as e:
        st.info(f"프리셋 시트가 없거나 로딩 실패 (선택사항): {str(e)}")
    
    return m_df, presets

# --- 3. UI 및 설정 ---
st.set_page_config(page_title="시디즈 마케팅 대시보드", layout="wide")

# Secrets 확인
try:
    required_keys = ["NAVER_API_KEY", "NAVER_SECRET_KEY", "NAVER_CUSTOMER_ID", 
                     "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"]
    keys = {k.lower(): st.secrets[k] for k in required_keys}
except KeyError as e:
    st.error(f"Secrets 설정 누락: {str(e)}")
    st.info("Settings > Secrets에서 다음 키를 설정하세요: " + ", ".join(required_keys))
    st.stop()
except Exception as e:
    st.error(f"Secrets 설정 오류: {str(e)}")
    st.stop()

with st.sidebar:
    st.header("⚙️ 기본 설정")
    sid = st.text_input("Sheet ID", "1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    unit = st.radio("집계 단위", ["일자별", "주차별", "월별"], index=2)
    s_date = st.date_input("시작일", datetime(2024, 12, 1))
    e_date = st.date_input("종료일", datetime(2025, 1, 31))
    
    if s_date >= e_date:
        st.error("시작일은 종료일보다 이전이어야 합니다")
    
    if st.button("🔄 전체 새로고침"): 
        st.cache_data.clear()
        st.rerun()

# 데이터 로딩
master_df, presets = load_all_data(sid)

if master_df.empty:
    st.error("데이터를 불러올 수 없습니다. Sheet ID와 시트 구조를 확인하세요.")
    st.stop()

# 세션 상태 관리
if 'active_groups' not in st.session_state: 
    st.session_state.active_groups = {}
if 'num_targets' not in st.session_state: 
    st.session_state.num_targets = 2

st.title("📊 시리즈별 마켓쉐어 상세 분석")

# --- 4. 프리셋 버튼 ---
if presets:
    st.subheader("⚡ 퀵 프리셋")
    p_cols = st.columns(min(len(presets), 5))
    for i, (name, items) in enumerate(presets.items()):
        with p_cols[i % 5]:
            if st.button(name, key=f"p_{i}", use_container_width=True):
                matched = master_df[
                    master_df['GROUP'].isin(items) | master_df['KEYWORD'].isin(items)
                ]
                st.session_state.num_targets = 1
                st.session_state.active_groups = {
                    "label_0": name,
                    "groups_0": matched['GROUP'].unique().tolist(),
                    "kws_0": matched['KEYWORD'].unique().tolist()
                }
                st.rerun()

st.markdown("---")

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
    headers = {
        'X-Timestamp': timestamp, 
        'X-API-KEY': api_key, 
        'X-Customer': customer_id, 
        'X-Signature': signature
    }
    params = {
        'hintKeywords': ",".join(keywords[:5]), 
        'showDetail': '1'
    }
    vols = {}
    try:
        res = requests.get(BASE_URL + uri, params=params, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        if 'keywordList' in data:
            for item in data['keywordList']:
                pc = str(item.get('monthlyPcQcCnt', '0')).replace('< ', '')
                mo = str(item.get('monthlyMobileQcCnt', '0')).replace('< ', '')
                try:
                    total = int(pc) + int(mo)
                except ValueError:
                    total = 0
                vols[item['relKeyword']] = total
    except requests.exceptions.RequestException as e:
        st.warning(f"검색량 API 오류: {str(e)}")
    except Exception as e:
        st.warning(f"데이터 처리 오류: {str(e)}")
    
    return vols

def get_datalab_trend(keyword, client_id, client_secret, start_date, end_date, time_unit):
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id": client_id, 
        "X-Naver-Client-Secret": client_secret, 
        "Content-Type": "application/json"
    }
    unit_map = {"일자별": "date", "주차별": "week", "월별": "month"}
    body = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "timeUnit": unit_map.get(time_unit, "month"),
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}]
    }
    try:
        res = requests.post(url, headers=headers, json=body, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        if 'results' in data and len(data['results']) > 0 and 'data' in data['results'][0]:
            return {d['period']: d['ratio'] for d in data['results'][0]['data']}
    except requests.exceptions.RequestException as e:
        st.warning(f"트렌드 API 오류 ({keyword}): {str(e)}")
    except Exception as e:
        st.warning(f"트렌드 처리 오류 ({keyword}): {str(e)}")
    
    return {}

# --- 2. 데이터 로딩 ---
@st.cache_data(ttl=600)
def load_all_data(sheet_id):
    try:
        main_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        m_df = pd.read_csv(main_url)
        m_df.columns = [c.strip().upper() for c in m_df.columns]
        
        # 필수 컬럼 확인
        if 'GROUP' not in m_df.columns or 'KEYWORD' not in m_df.columns:
            st.error(f"스프레드시트에 'GROUP', 'KEYWORD' 컬럼이 필요합니다. 현재 컬럼: {m_df.columns.tolist()}")
            return pd.DataFrame(), {}
        
    except Exception as e:
        st.error(f"메인 시트 로딩 실패: {str(e)}")
        return pd.DataFrame(), {}
    
    # 프리셋 로딩
    presets = {}
    try:
        preset_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=PRESETS"
        p_df = pd.read_csv(preset_url)
        p_df.columns = [c.strip().upper() for c in p_df.columns]
        
        name_col = next((c for c in p_df.columns if 'NAME' in c), None)
        kw_col = next((c for c in p_df.columns if 'KEYWORD' in c), None)
        
        if name_col and kw_col:
            for _, row in p_df.iterrows():
                name = str(row[name_col]).strip()
                keywords = str(row[kw_col]).strip()
                if name and keywords and name != 'nan' and keywords != 'nan':
                    presets[name] = [k.strip() for k in keywords.split(',') if k.strip()]
    except Exception as e:
        st.info(f"프리셋 시트가 없거나 로딩 실패 (선택사항): {str(e)}")
    
    return m_df, presets

# --- 3. UI 및 설정 ---
st.set_page_config(page_title="시디즈 마케팅 대시보드", layout="wide")

# Secrets 확인
try:
    required_keys = ["NAVER_API_KEY", "NAVER_SECRET_KEY", "NAVER_CUSTOMER_ID", 
                     "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"]
    keys = {k.lower(): st.secrets[k] for k in required_keys}
except KeyError as e:
    st.error(f"Secrets 설정 누락: {str(e)}")
    st.info("Settings > Secrets에서 다음 키를 설정하세요: " + ", ".join(required_keys))
    st.stop()
except Exception as e:
    st.error(f"Secrets 설정 오류: {str(e)}")
    st.stop()

with st.sidebar:
    st.header("⚙️ 기본 설정")
    sid = st.text_input("Sheet ID", "1JnEKEe7HDbN5NG8l0kZ55Rtihp9SBbauD0CzhKQX-qM")
    unit = st.radio("집계 단위", ["일자별", "주차별", "월별"], index=2)
    s_date = st.date_input("시작일", datetime(2024, 12, 1))
    e_date = st.date_input("종료일", datetime(2025, 1, 31))
    
    if s_date >= e_date:
        st.error("시작일은 종료일보다 이전이어야 합니다")
    
    if st.button("🔄 전체 새로고침"): 
        st.cache_data.clear()
        st.rerun()

# 데이터 로딩
master_df, presets = load_all_data(sid)

if master_df.empty:
    st.error("데이터를 불러올 수 없습니다. Sheet ID와 시트 구조를 확인하세요.")
    st.stop()

# 세션 상태 관리
if 'active_groups' not in st.session_state: 
    st.session_state.active_groups = {}
if 'num_targets' not in st.session_state: 
    st.session_state.num_targets = 2

st.title("📊 시리즈별 마켓쉐어 상세 분석")

# --- 4. 프리셋 버튼 ---
if presets:
    st.subheader("⚡ 퀵 프리셋")
    p_cols = st.columns(min(len(presets), 5))
    for i, (name, items) in enumerate(presets.items()):
        with p_cols[i % 5]:
            if st.button(name, key=f"p_{i}", use_container_width=True):
                matched = master_df[
                    master_df['GROUP'].isin(items) | master_df['KEYWORD'].isin(items)
                ]
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
num_targets = st.number_input(
    "분석 대상 개수", 
    min_value=1, 
    max_value=5, 
    value=st.session_state.num_targets
)
st.session_state.num_targets = num_targets

final_filter = {}
group_options = sorted([g for g in master_df['GROUP'].unique() if pd.notna(g)])

# 디버깅용 정보 표시
with st.expander("🔍 데이터 확인 (디버깅)"):
    st.write(f"총 그룹 수: {len(group_options)}")
    st.write(f"총 키워드 수: {len(master_df['KEYWORD'].unique())}")
    st.write("그룹 목록:", group_options[:10])
    st.write("첫 5행 데이터:")
    st.dataframe(master_df.head())

cols = st.columns(num_targets)

for i in range(num_targets):
    with cols[i]:
        def_label = st.session_state.active_groups.get(f"label_{i}", f"비교군 {i+1}")
        def_groups = st.session_state.active_groups.get(f"groups_{i}", [])
        def_kws = st.session_state.active_groups.get(f"kws_{i}", [])

        label = st.text_input(f"대상 {i+1} 이름", value=def_label, key=f"lab_{i}")
        
        # 그룹 선택 없을 때 안내 메시지
        if not group_options:
            st.error("사용 가능한 그룹이 없습니다. 스프레드시트 데이터를 확인하세요.")
            continue
            
        sel_groups = st.multiselect(
            f"그룹(브랜드) 선택", 
            options=group_options, 
            default=[g for g in def_groups if g in group_options], 
            key=f"gr_{i}",
            help="먼저 그룹을 선택하세요"
        )
        
        if sel_groups:
            kw_options = sorted([
                k for k in master_df[master_df['GROUP'].isin(sel_groups)]['KEYWORD'].unique() 
                if pd.notna(k)
            ])
            
            if not kw_options:
                st.warning("선택한 그룹에 키워드가 없습니다.")
                continue
                
            current_def = [k for k in def_kws if k in kw_options] if def_kws else []
            sel_kws = st.multiselect(
                f"키워드 선택", 
                options=kw_options, 
                default=current_def if current_def else kw_options[:min(3, len(kw_options))], 
                key=f"kw_{i}",
                help=f"선택 가능한 키워드: {len(kw_options)}개"
            )
            
            # 라벨과 키워드가 모두 있을 때만 추가
            if label and label.strip() and sel_kws:
                final_filter[label] = sel_kws
                st.success(f"✅ {len(sel_kws)}개 키워드 선택됨")
        else:
            st.info("⬆️ 그룹을 먼저 선택하세요")

# 디버깅: final_filter 상태 표시
st.markdown("---")
if final_filter:
    st.success(f"✅ 총 {len(final_filter)}개 분석 대상이 설정되었습니다")
    with st.expander("선택된 분석 대상 확인"):
        for label, kws in final_filter.items():
            st.write(f"**{label}**: {len(kws)}개 키워드")
            st.write(", ".join(kws[:5]) + ("..." if len(kws) > 5 else ""))
else:
    st.warning("⚠️ 분석 대상이 설정되지 않았습니다. 위에서 그룹과 키워드를 선택하세요.")

# --- 6. 분석 실행 ---
if final_filter:
    if st.button("🚀 분석 시작", type="primary", use_container_width=True):
        results = []
        all_unique_kws = list(set([kw for kws in final_filter.values() for kw in kws]))
        
        if len(all_unique_kws) > 50:
            st.warning(f"선택한 키워드가 {len(all_unique_kws)}개입니다. 50개 이하로 줄이는 것을 권장합니다.")
        
        progress = st.progress(0)
        status = st.empty()
        
        # 1단계: 검색량 조회
        all_vols = {}
        for i in range(0, len(all_unique_kws), 5):
            chunk = all_unique_kws[i:i+5]
            status.text(f"🔍 네이버 검색량 데이터 수집 중... ({min(i+5, len(all_unique_kws))}/{len(all_unique_kws)})")
            chunk_vols = get_naver_search_vols_bulk(
                chunk, 
                keys["naver_api_key"], 
                keys["naver_secret_key"], 
                keys["naver_customer_id"]
            )
            all_vols.update(chunk_vols)
            progress.progress(min((i+5)/(len(all_unique_kws)*2), 0.4))
            time.sleep(0.3)

        # 2단계: 트렌드 조회
        current_idx = 0
        total_kws = len(all_unique_kws)
        
        for group_label, kws in final_filter.items():
            for kw in kws:
                current_idx += 1
                status.text(f"⏳ [{group_label}] 분석 중: {kw} ({current_idx}/{total_kws})")
                
                vol = all_vols.get(kw, 0)
                trends = get_datalab_trend(
                    kw, 
                    keys["naver_client_id"], 
                    keys["naver_client_secret"], 
                    s_date, 
                    e_date, 
                    unit
                )
                
                if trends:
                    total_r = sum(trends.values())
                    for p, r in trends.items():
                        results.append({
                            "분석대상": group_label, 
                            "기간": p, 
                            "키워드": kw,
                            "검색량": int((r/total_r)*vol) if total_r > 0 else 0
                        })
                elif vol > 0:
                    results.append({
                        "분석대상": group_label, 
                        "기간": s_date.strftime("%Y-%m-%d"), 
                        "키워드": kw,
                        "검색량": vol
                    })
                
                progress.progress(0.4 + (current_idx / total_kws * 0.6))
                time.sleep(0.15)

        status.empty()
        progress.empty()

        if results:
            df = pd.DataFrame(results)
            df_grp = df.groupby(['기간', '분석대상'])['검색량'].sum().reset_index()
            
            period_totals = df_grp.groupby('기간')['검색량'].transform('sum')
            df_grp['비중'] = ((df_grp['검색량'] / period_totals * 100).fillna(0)).round(1)
            
            fig = px.bar(
                df_grp, 
                x="검색량", 
                y="기간", 
                color="분석대상", 
                orientation='h', 
                barmode='stack',
                text=df_grp.apply(lambda x: f"{x['검색량']:,} ({x['비중']}%)", axis=1), 
                height=max(600, len(df_grp['기간'].unique()) * 40),
                color_discrete_sequence=px.colors.qualitative.Pastel,
                title="기간별 검색량 및 점유율"
            )
            fig.update_traces(textposition='inside')
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("📋 상세 데이터")
            pivot_df = df.pivot_table(
                index=["분석대상", "키워드"], 
                columns="기간", 
                values="검색량", 
                aggfunc="sum",
                fill_value=0
            )
            st.dataframe(pivot_df, use_container_width=True)
            
            st.subheader("📈 요약")
            summary = df.groupby('분석대상')['검색량'].sum().sort_values(ascending=False)
            st.dataframe(summary.rename("총 검색량"), use_container_width=True)
            
        else:
            st.error("데이터를 수집하지 못했습니다. 다음을 확인하세요:")
            st.markdown("""
            - API 키가 올바른지 확인
            - 키워드가 존재하는지 확인
            - 날짜 범위가 적절한지 확인
            - 네트워크 연결 확인
            """)
else:
    st.info("👆 분석 대상을 설정하고 '분석 시작' 버튼을 눌러주세요.")

# --- 6. 분석 실행 ---
st.markdown("---")
if final_filter:
    if st.button("🚀 분석 시작", type="primary", use_container_width=True):
        results = []
        all_unique_kws = list(set([kw for kws in final_filter.values() for kw in kws]))
        
        if len(all_unique_kws) > 50:
            st.warning(f"선택한 키워드가 {len(all_unique_kws)}개입니다. 50개 이하로 줄이는 것을 권장합니다.")
        
        progress = st.progress(0)
        status = st.empty()
        
        # 1단계: 검색량 조회
        all_vols = {}
        for i in range(0, len(all_unique_kws), 5):
            chunk = all_unique_kws[i:i+5]
            status.text(f"🔍 네이버 검색량 데이터 수집 중... ({min(i+5, len(all_unique_kws))}/{len(all_unique_kws)})")
            chunk_vols = get_naver_search_vols_bulk(
                chunk, 
                keys["naver_api_key"], 
                keys["naver_secret_key"], 
                keys["naver_customer_id"]
            )
            all_vols.update(chunk_vols)
            progress.progress(min((i+5)/(len(all_unique_kws)*2), 0.4))
            time.sleep(0.3)  # API 부하 방지

        # 2단계: 트렌드 조회
        current_idx = 0
        total_kws = len(all_unique_kws)
        
        for group_label, kws in final_filter.items():
            for kw in kws:
                current_idx += 1
                status.text(f"⏳ [{group_label}] 분석 중: {kw} ({current_idx}/{total_kws})")
                
                vol = all_vols.get(kw, 0)
                trends = get_datalab_trend(
                    kw, 
                    keys["naver_client_id"], 
                    keys["naver_client_secret"], 
                    s_date, 
                    e_date, 
                    unit
                )
                
                if trends:
                    total_r = sum(trends.values())
                    for p, r in trends.items():
                        results.append({
                            "분석대상": group_label, 
                            "기간": p, 
                            "키워드": kw,
                            "검색량": int((r/total_r)*vol) if total_r > 0 else 0
                        })
                elif vol > 0:
                    # 트렌드 없지만 검색량이 있는 경우
                    results.append({
                        "분석대상": group_label, 
                        "기간": s_date.strftime("%Y-%m-%d"), 
                        "키워드": kw,
                        "검색량": vol
                    })
                
                progress.progress(0.4 + (current_idx / total_kws * 0.6))
                time.sleep(0.15)  # API 부하 방지

        status.empty()
        progress.empty()

        if results:
            df = pd.DataFrame(results)
            df_grp = df.groupby(['기간', '분석대상'])['검색량'].sum().reset_index()
            
            # 비중 계산 (0으로 나누기 방지)
            period_totals = df_grp.groupby('기간')['검색량'].transform('sum')
            df_grp['비중'] = ((df_grp['검색량'] / period_totals * 100).fillna(0)).round(1)
            
            # 그래프 생성
            fig = px.bar(
                df_grp, 
                x="검색량", 
                y="기간", 
                color="분석대상", 
                orientation='h', 
                barmode='stack',
                text=df_grp.apply(lambda x: f"{x['검색량']:,} ({x['비중']}%)", axis=1), 
                height=max(600, len(df_grp['기간'].unique()) * 40),
                color_discrete_sequence=px.colors.qualitative.Pastel,
                title="기간별 검색량 및 점유율"
            )
            fig.update_traces(textposition='inside')
            st.plotly_chart(fig, use_container_width=True)
            
            # 상세 데이터 테이블
            st.subheader("📋 상세 데이터")
            pivot_df = df.pivot_table(
                index=["분석대상", "키워드"], 
                columns="기간", 
                values="검색량", 
                aggfunc="sum",
                fill_value=0
            )
            st.dataframe(pivot_df, use_container_width=True)
            
            # 요약 통계
            st.subheader("📈 요약")
            summary = df.groupby('분석대상')['검색량'].sum().sort_values(ascending=False)
            st.dataframe(summary.rename("총 검색량"), use_container_width=True)
            
        else:
            st.error("데이터를 수집하지 못했습니다. 다음을 확인하세요:")
            st.markdown("""
            - API 키가 올바른지 확인
            - 키워드가 존재하는지 확인
            - 날짜 범위가 적절한지 확인 (너무 긴 기간은 피하세요)
            - 네트워크 연결 확인
            """)
else:
    st.info("분석 대상을 설정하고 '분석 시작' 버튼을 눌러주세요.")
