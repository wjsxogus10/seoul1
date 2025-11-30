import streamlit as st
import pandas as pd
import geopandas
import plotly.express as px
import plotly.graph_objects as go
import os
import requests
import io
from shapely.geometry import Point

# --------------------------------------------------------------------------
# 1. 페이지 기본 설정
# --------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="서울시 도시계획 대시보드")
st.title("🏙️ 서울시 도시계획 및 대중교통 개선 대시보드")

# --------------------------------------------------------------------------
# 2. 데이터 로드 및 병합 함수
# --------------------------------------------------------------------------
@st.cache_data(show_spinner="데이터를 로드하고 분석을 진행합니다...")
def load_and_merge_data():
    # (A) 지도 데이터
    map_url = "https://raw.githubusercontent.com/southkorea/seoul-maps/master/kostat/2013/json/seoul_municipalities_geo_simple.json"
    try:
        response = requests.get(map_url)
        response.raise_for_status()
        gdf = geopandas.read_file(io.BytesIO(response.content))
        gdf = gdf.to_crs(epsg=4326)
        
        if 'name' in gdf.columns: gdf['자치구명'] = gdf['name']
        elif 'SIG_KOR_NM' in gdf.columns: gdf['자치구명'] = gdf['SIG_KOR_NM']
        else: return None, None, None
            
        gdf['면적(km²)'] = gdf.geometry.to_crs(epsg=5179).area / 1_000_000
    except Exception as e:
        st.error(f"❌ 지도 로드 실패: {e}")
        return None, None, None

    # (B) 데이터 병합 준비
    cols_init = ['총_상주인구_수', '인구 밀도', '집객시설 수', '버스정류장_수', '버스정류장 밀도', '지하철역_수', '지하철역 밀도', '총_교통수단_수', '대중교통 밀도']
    for c in cols_init:
        if c not in gdf.columns: gdf[c] = 0

    # 1. 상주 인구
    try:
        df = pd.read_csv('./data/서울시 상권분석서비스(상주인구-자치구).csv', encoding='cp949')
        grp = df.groupby('자치구_코드_명')['총_상주인구_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.merge(grp, on='자치구명', how='left', suffixes=('', '_new'))
        if '총_상주인구_수_new' in gdf.columns:
            gdf['총_상주인구_수'] = gdf['총_상주인구_수_new'].fillna(0)
        gdf['인구 밀도'] = gdf['총_상주인구_수'] / gdf['면적(km²)']
    except: pass

    # 2. 집객시설
    try:
        df = pd.read_csv('./data/서울시 상권분석서비스(집객시설-자치구).csv', encoding='cp949')
        val = next((c for c in df.columns if '집객' in c or '시설' in c), None)
        nm = next((c for c in df.columns if '자치구' in c), None)
        if val and nm:
            grp = df.groupby(nm)[val].mean().reset_index().rename(columns={nm:'자치구명', val:'집객시설 수'})
            gdf = gdf.merge(grp, on='자치구명', how='left', suffixes=('', '_new'))
            if '집객시설 수_new' in gdf.columns:
                gdf['집객시설 수'] = gdf['집객시설 수_new'].fillna(0)
    except: pass

    # 3. 버스 정류장 (좌표 보정 + 점 데이터 생성)
    df_bus_stations = pd.DataFrame()
    try:
        bus_path = './data/GGD_StationInfo_M.xlsx'
        if os.path.exists(bus_path):
            df_bus = pd.read_excel(bus_path).dropna(subset=['X', 'Y'])
            
            # 좌표계 후보군 테스트 (5181, 5179, 4326)
            crs_list = ['EPSG:5181', 'EPSG:5179', 'EPSG:4326']
            success = False
            
            for crs_code in crs_list:
                try:
                    # Case 1: X, Y
