import streamlit as st
import pandas as pd
import geopandas
import plotly.express as px
import plotly.graph_objects as go
import os
from shapely.geometry import Point
import numpy as np

# --------------------------------------------------------------------------
# 1. 페이지 설정
# --------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="서울시 대중교통 개선 대시보드")

# --------------------------------------------------------------------------
# 2. 데이터 로드 및 병합 함수
# --------------------------------------------------------------------------
@st.cache_data(ttl=600)
def load_and_merge_data():
    logs = []
    data_info = {} # 데이터 정보 저장

    # [헬퍼 함수] 숫자 변환 (콤마 제거)
    def clean_numeric(value):
        if isinstance(value, str):
            try: return float(value.replace(',', '').strip())
            except: return 0
        return value

    # [A] 지도 데이터
    map_url = "https://raw.githubusercontent.com/southkorea/seoul-maps/master/kostat/2013/json/seoul_municipalities_geo_simple.json"
    try:
        gdf = geopandas.read_file(map_url)
        gdf = gdf.to_crs(epsg=4326)
        if 'name' in gdf.columns: gdf = gdf.rename(columns={'name': '자치구명'})
        elif 'SIG_KOR_NM' in gdf.columns: gdf = gdf.rename(columns={'SIG_KOR_NM': '자치구명'})
        gdf_area = gdf.to_crs(epsg=5179)
        gdf['면적(km²)'] = gdf_area.geometry.area / 1_000_000
        data_info['지도'] = {'file': 'seoul_municipalities_geo_simple.json', 'status': '✅'}
    except Exception as e:
        return None, [f"❌ 지도 로드 실패: {e}"], {}

    # [B] 사용자 데이터 병합 (초기화)
    cols_init = ['총_상주인구_수', '인구 밀도', '집객시설 수', '버스정류장_수', '버스정류장 밀도', '지하철역_수', '지하철역 밀도', '총_교통수단_수']
    for c in cols_init: gdf[c] = 0

    # 1. 인구
    pop_file = '서울시 상권분석서비스(상주인구-자치구).csv'
    pop_path = None
    if os.path.exists(pop_file): pop_path = pop_file
    elif os.path.exists(f'./data/{pop_file}'): pop_path = f'./data/{pop_file}'

    if pop_path:
        try:
            df_pop = pd.read_csv(pop_path, encoding='cp949')
            # 컬럼명 공백 제거 및 숫자 변환
            df_pop.columns = df_pop.columns.str.strip()
            if '총_상주인구_수' in df_pop.columns:
                df_pop['총_상주인구_수'] = df_pop['총_상주인구_수'].apply(clean_numeric)
            
            grp = df_pop.groupby('자치구_코드_명')['총_상주인구_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
            gdf = gdf.drop(columns=['총_상주인구_수', '인구 밀도'], errors='ignore')
            gdf = gdf.merge(grp, on='자치구명', how='left')
            gdf['총_상주인구_수'] = gdf['총_상주인구_수'].fillna(0)
            gdf['인구 밀도'] = gdf['총_상주인구_수'] / gdf['면적(km²)']
            data_info['인구'] = {'file': pop_file, 'status': '✅'}
        except: 
            data_info['인구'] = {'file': pop_file, 'status': '❌ 읽기 실패'}
    else:
        data_info['인구'] = {'file': pop_file, 'status': '❌ (파일 없음)'}

    # 2. 상권
    biz_file = '서울시 상권분석서비스(집객시설-자치구).csv'
    biz_path = None
    if os.path.exists(biz_file): biz_path = biz_file
    elif os.path.exists(f'./data/{biz_file}'): biz_path = f'./data/{biz_file}'

    if biz_path:
        try:
            df_biz = pd.read_csv(biz_path, encoding='cp949')
            grp = df_biz.groupby('자치구_코드_명')['집객시설_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
            gdf = gdf.drop(columns=['집객시설 수'], errors='ignore')
            gdf = gdf.merge(grp, on='자치구명', how='left')
            gdf['집객시설 수'] = gdf['집객시설_수'].fillna(0)
            data_info['상권'] = {'file': biz_file, 'status': '✅'}
        except:
            data_info['상권'] = {'file': biz_file, 'status': '❌'}
    else:
        data_info['상권'] = {'file': biz_file, 'status': '❌ (파일 없음)'}
