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
            # '< 10' 같은 문자열 처리
            pc_val = str(target['monthlyPcQcCnt']).replace('< ', '')
            mo_val = str(target['monthlyMobileQcCnt']).replace('< ', '')
            
            return {
                "pc": int(pc_val) if pc_val.isdigit() else 10,
                "mobile": int(mo_val) if mo_val.isdigit() else 10
            }
    except Exception as e:
        pass # 에러 발생 시 아래 기본값 반환
        
    return {"pc": 0, "mobile": 0}

# --- 2. 데이터 로딩 (구글 시트) ---
@st.cache_data
def load_data_from_gsheets(sheet_id):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    df = pd.read_csv(url)
    return df

# --- 3. UI 구성 ---
st.set_page_config(page_title="의자 키워드 비교 분석기", layout="wide")

with st.sidebar:
    st.header("🔑 API 및 데이터 설정")
    # 팁: 매번 입력하기 귀찮다면 value="내키값"을
