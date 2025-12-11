import streamlit as st
import pandas as pd
import geopandas
import plotly.express as px
import os
from shapely.geometry import Point

# --------------------------------------------------------------------------
# 1. 기본 설정
# --------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="서울시 도시계획 대시보드")
st.title("🏙️ 서울시 도시계획 및 대중교통 개선 대시보드")

# --------------------------------------------------------------------------
# 2. 데이터 로드 및 전처리
# --------------------------------------------------------------------------
@st.cache_data
def load_and_merge_data():
    # -----------------------------------------------------------
    # (A) 지도 데이터 (인터넷 공공 데이터)
    # -----------------------------------------------------------
    map_url = "https://raw.githubusercontent.com/southkorea/seoul-maps/master/kostat/2013/json/seoul_municipalities_geo_simple.json"
    try:
        gdf = geopandas.read_file(map_url)
        gdf = gdf.to_crs(epsg=4326)
        
        # 컬럼 통일
        col_map = {'name': '자치구명', 'SIG_KOR_NM': '자치구명'}
        gdf = gdf.rename(columns=col_map)
        
        # 면적 계산
        gdf_area = gdf.to_crs(epsg=5179)
        gdf['면적(km²)'] = gdf_area.geometry.area / 1_000_000
    except Exception as e:
        st.error(f"지도 로드 실패: {e}")
        return None

    # -----------------------------------------------------------
    # (B) 사용자 데이터 병합
    # -----------------------------------------------------------
    
    # 1. 인구 데이터
    pop_file = './data/서울시 상권분석서비스(상주인구-자치구).csv'
    if os.path.exists(pop_file):
        try:
            df_pop = pd.read_csv(pop_file, encoding='cp949')
            df_grp = df_pop.groupby('자치구_코드_명')['총_상주인구_수'].mean().reset_index()
            df_grp.rename(columns={'자치구_코드_명': '자치구명'}, inplace=True)
            gdf = gdf.merge(df_grp, on='자치구명', how='left')
            gdf['인구 밀도'] = gdf['총_상주인구_수'] / gdf['면적(km²)']
        except: pass

    # 2. 상권 데이터
    biz_file = './data/서울시 상권분석서비스(집객시설-자치구).csv'
    if os.path.exists(biz_file):
        try:
            df_biz = pd.read_csv(biz_file, encoding='cp949')
            df_grp = df_biz.groupby('자치구_코드_명')['집객시설_수'].mean().reset_index()
            df_grp.rename(columns={'자치구_코드_명': '자치구명'}, inplace=True)
            gdf = gdf.merge(df_grp, on='자치구명', how='left')
        except: pass

    # 3. 버스 데이터
    bus_file = './data/GGD_StationInfo_M.xlsx'
    if os.path.exists(bus_file):
        try:
            df = pd.read_excel(bus_file)
            df = df.dropna(subset=['X', 'Y'])
            geom = [Point(xy) for xy in zip(df['X'], df['Y'])]
            gdf_bus = geopandas.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")
            joined = geopandas.sjoin(gdf_bus, gdf, how="inner", predicate="within")
            cnt = joined.groupby('자치구명').size().reset_index(name='버스정류장 수')
            gdf = gdf.merge(cnt, on='자치구명', how='left')
            gdf['버스정류장 수'] = gdf['버스정류장 수'].fillna(0)
            gdf['버스 밀도'] = gdf['버스정류장 수'] / gdf['면적(km²)']
        except: pass

    # 4. 지하철 데이터 (자동 찾기)
    subway_files = [f for f in os.listdir('./data') if 'subway' in f.lower() or '지하철' in f]
    if subway_files:
        try:
            f_path = os.path.join('./data', subway_files[0])
            if f_path.endswith('.csv'): df_sub = pd.read_csv(f_path, encoding='cp949')
            else: df_sub = pd.read_excel(f_path)
            
            x_col = next((c for c in ['경도', 'X', 'lon', 'x'] if c in df_sub.columns), None)
            y_col = next((c for c in ['위도', 'Y', 'lat', 'y'] if c in df_sub.columns), None)

            if x_col and y_col:
                df_sub = df_sub.dropna(subset=[x_col, y_col])
                geom = [Point(xy) for xy in zip(df_sub[x_col], df_sub[y_col])]
                gdf_sub = geopandas.GeoDataFrame(df_sub, geometry=geom, crs="EPSG:4326")
                joined = geopandas.sjoin(gdf_sub, gdf, how="inner", predicate="within")
                cnt = joined.groupby('자치구명').size().reset_index(name='지하철역 수')
                gdf = gdf.merge(cnt, on='자치구명', how='left')
                gdf['지하철역 수'] = gdf['지하철역 수'].fillna(0)
                gdf['지하철 밀도'] = gdf['지하철역 수'] / gdf['면적(km²)']
        except: pass
    else:
        gdf['지하철역 수'] = 0
        gdf['지하철 밀도'] = 0

    # -----------------------------------------------------------
    # [핵심] 컬럼 이름 깔끔하게 바꾸기 (언더바 제거)
    # -----------------------------------------------------------
    rename_map = {
        '총_상주인구_수': '총 상주인구',
        '집객시설_수': '집객시설 수',
        '면적(km²)': '면적',
        '인구_밀도(명/km²)': '인구 밀도', # 위에서 이미 '인구 밀도'로 만듦
        '버스정류장_수': '버스정류장 수',
        '버스정류장_밀도(개/km²)': '버스 밀도',
        '지하철역_수': '지하철역 수',
        '지하철역_밀도(개/km²)': '지하철 밀도'
    }
    gdf = gdf.rename(columns=rename_map)
    
    # 교통 부족 순위 계산 (깔끔한 이름 사용)
    if '정류장 수' not in gdf.columns: # 위에서 rename되면서 이름 바뀜
        # 혹시 모르니 체크, 보통 버스와 지하철 합쳐서 계산
        gdf['총 정류장 수'] = gdf.get('버스정류장 수', 0) + gdf.get('지하철역 수', 0)
        gdf['교통 부족 순위'] = gdf['총 정류장 수'].rank(ascending=True, method='min')

    return gdf

# --------------------------------------------------------------------------
# 3. 화면 구성
# --------------------------------------------------------------------------
gdf = load_and_merge_data()

if gdf is not None:
    st.sidebar.header("🔍 분석 옵션")
    
    # 분석 가능한 지표 자동 찾기
    possible_metrics = ['인구 밀도', '버스 밀도', '지하철 밀도', '총 상주인구', '집객시설 수', '교통 부족 순위']
    valid_metrics = [m for m in possible_metrics if m in gdf.columns]
    
    selected_metric = st.sidebar.radio("분석할 지표", valid_metrics)
    
    district_list = ['전체 서울시'] + sorted(gdf['자치구명'].unique().tolist())
    selected_district = st.sidebar.selectbox("자치구 상세", district_list)

    # (1) 지도
    st.subheader(f"🗺️ 서울시 {selected_metric} 지도")
    
    center_lat, center_lon, zoom = 37.5665, 126.9780, 9.5
    if selected_district != '전체 서울시':
        d = gdf[gdf['자치구명'] == selected_district]
        center_lat, center_lon = d.geometry.centroid.y.values[0], d.geometry.centroid.x.values[0]
        zoom = 11.5

    fig = px.choropleth_mapbox(
        gdf, geojson=gdf.geometry.__geo_interface__, locations=gdf.index,
        color=selected_metric, mapbox_style="carto-positron", zoom=zoom,
        center={"lat": center_lat, "lon": center_lon}, opacity=0.6,
        hover_name='자치구명', 
        hover_data=valid_metrics, # 툴팁에 모든 지표 깔끔하게 표시
        color_continuous_scale='YlGnBu'
    )
    fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=500)
    st.plotly_chart(fig, use_container_width=True)

    # (2) 그래프
    st.subheader(f"📊 {selected_metric} 순위")
    sort_opt = st.radio("정렬:", ["상위 10개", "하위 10개", "전체"], horizontal=True)
    df_sorted = gdf.sort_values(by=selected_metric, ascending=False)
    
    if sort_opt == "상위 10개": data = df_sorted.head(10)
    elif sort_opt == "하위 10개": data = df_sorted.tail(10).sort_values(by=selected_metric)
    else: data = df_sorted
    
    data['color'] = data['자치구명'].apply(lambda x: 'red' if x == selected_district else 'blue')
    
    fig_bar = px.bar(data, x='자치구명', y=selected_metric, color='color', 
                     color_discrete_map={'red':'#FF4B4B', 'blue':'#8884d8'},
                     title=f"{selected_metric} 자치구별 비교")
    fig_bar.update_layout(showlegend=False, xaxis_title="자치구", yaxis_title=selected_metric)
    st.plotly_chart(fig_bar, use_container_width=True)

    # (3) 표 (인덱스 숨김 기능 추가!)
    st.markdown("---")
    st.subheader("📋 전체 데이터 표")
    
    cols = ['자치구명'] + valid_metrics
    st.dataframe(
        gdf[cols].sort_values(by=selected_metric, ascending=False),
        use_container_width=True,
        hide_index=True  # <--- [핵심] 인덱스(0,1,2...) 숨기기
    )
    
    csv = gdf[cols].to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 엑셀(CSV) 다운로드", csv, "seoul_data.csv", "text/csv")
