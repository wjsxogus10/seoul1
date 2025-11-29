import streamlit as st
import pandas as pd
import geopandas
import plotly.express as px
import plotly.graph_objects as go
import os

# --------------------------------------------------------------------------
# 1. 페이지 기본 설정
# --------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="서울시 도시계획 대시보드")
st.title("🏙️ 서울시 도시계획 및 대중교통 개선 대시보드")

# --------------------------------------------------------------------------
# 2. 데이터 로드 및 병합 함수
# --------------------------------------------------------------------------
@st.cache_data
def load_and_merge_data():
    # (A) 지도 데이터
    map_url = "https://raw.githubusercontent.com/southkorea/seoul-maps/master/kostat/2013/json/seoul_municipalities_geo_simple.json"
    try:
        gdf = geopandas.read_file(map_url)
        gdf = gdf.to_crs(epsg=4326)
        
        if 'name' in gdf.columns:
            gdf = gdf.rename(columns={'name': '자치구명'})
        elif 'SIG_KOR_NM' in gdf.columns:
            gdf = gdf.rename(columns={'SIG_KOR_NM': '자치구명'})
            
        gdf_area = gdf.to_crs(epsg=5179)
        gdf['면적(km²)'] = gdf_area.geometry.area / 1_000_000
    except Exception as e:
        st.error(f"지도 로드 실패: {e}")
        return None, None

    # (B) 사용자 데이터 병합
    
    # 컬럼 초기화
    cols_init = ['총_상주인구_수', '인구 밀도', '집객시설 수', '버스정류장_수', '버스정류장 밀도', '지하철역_수', '지하철역 밀도']
    for c in cols_init:
        gdf[c] = 0
    
    # 1. 상주 인구
    try:
        df_pop = pd.read_csv('./data/서울시 상권분석서비스(상주인구-자치구).csv', encoding='cp949')
        grp = df_pop.groupby('자치구_코드_명')['총_상주인구_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.drop(columns=['총_상주인구_수', '인구 밀도'], errors='ignore')
        gdf = gdf.merge(grp, on='자치구명', how='left')
        gdf['총_상주인구_수'] = gdf['총_상주인구_수'].fillna(0)
        gdf['인구 밀도'] = gdf['총_상주인구_수'] / gdf['면적(km²)']
    except: pass

    # 2. 집객시설 수
    try:
        df_biz = pd.read_csv('./data/서울시 상권분석서비스(집객시설-자치구).csv', encoding='cp949')
        grp = df_biz.groupby('자치구_코드_명')['집객시설_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.drop(columns=['집객시설 수'], errors='ignore')
        gdf = gdf.merge(grp, on='자치구명', how='left')
        gdf['집객시설 수'] = gdf['집객시설 수'].fillna(0)
    except: pass

    # 3. 버스정류장 밀도
    try:
        from shapely.geometry import Point
        df_bus = pd.read_excel('./data/GGD_StationInfo_M.xlsx').dropna(subset=['X', 'Y'])
        geom = [Point(xy) for xy in zip(df_bus['X'], df_bus['Y'])]
        gdf_bus = geopandas.GeoDataFrame(df_bus, geometry=geom, crs="EPSG:4326")
        joined = geopandas.sjoin(gdf_bus, gdf, how="inner", predicate="within")
        cnt = joined.groupby('자치구명').size().reset_index(name='버스정류장_수')
        
        gdf = gdf.drop(columns=['버스정류장_수', '버스정류장 밀도'], errors='ignore')
        gdf = gdf.merge(cnt, on='자치구명', how='left')
        gdf['버스정류장_수'] = gdf['버스정류장_수'].fillna(0)
        gdf['버스정류장 밀도'] = gdf['버스정류장_수'] / gdf['면적(km²)']
    except: 
        gdf['버스정류장 밀도'] = 0

    # 4. 지하철 밀도
    density_file = './data/지하철 밀도.CSV'
    if os.path.exists(density_file):
        try:
            try: df_dens = pd.read_csv(density_file, encoding='utf-8')
            except: df_dens = pd.read_csv(density_file, encoding='cp949')
            
            gu_col = next((c for c in df_dens.columns if '자치구' in c), None)
            dens_col = next((c for c in df_dens.columns if '밀도' in c), None)
            cnt_col = next((c for c in df_dens.columns if '역' in c and '수' in c), None)
            
            if gu_col and dens_col:
                rename_map = {gu_col: '자치구명', dens_col: '지하철역 밀도'}
                if cnt_col: rename_map[cnt_col] = '지하철역_수'
                
                df_dens = df_dens.rename(columns=rename_map)
                
                gdf = gdf.drop(columns=['지하철역_수', '지하철역 밀도'], errors='ignore')
                gdf = gdf.merge(df_dens[['자치구명', '지하철역 밀도', '지하철역_수']], on='자치구명', how='left')
                gdf['지하철역 밀도'] = gdf['지하철역 밀도'].fillna(0)
                gdf['지하철역_수'] = gdf['지하철역_수'].fillna(0)
            else:
                gdf['지하철역 밀도'] = 0
        except: 
            gdf['지하철역 밀도'] = 0

    # 5. 지하철 위치 좌표
    coord_file = './data/지하철 위경도.CSV'
    df_stations = pd.DataFrame()
    if os.path.exists(coord_file):
        try:
            df_stations = pd.read_csv(coord_file, encoding='utf-8')
            if 'point_x' not in df_stations.columns: df_stations = pd.DataFrame()
        except: pass

    # 6. 대중교통 밀도 & 교통 부족 순위
    if '버스정류장 밀도' not in gdf.columns: gdf['버스정류장 밀도'] = 0
    if '지하철역 밀도' not in gdf.columns: gdf['지하철역 밀도'] = 0
    if '총_상주인구_수' not in gdf.columns: gdf['총_상주인구_수'] = 0
    
    # 총 교통수단 수
    gdf['총_교통수단_수'] = gdf['버스정류장_수'] + gdf['지하철역_수']

    # 면적당 밀도
    gdf['대중교통 밀도'] = gdf['총_교통수단_수'] / gdf['면적(km²)']
    
    # 인구 대비 교통수단 비율
    population_safe = gdf['총_상주인구_수'].replace(0, 1)
    gdf['인구 대비 교통수단 비율'] = gdf['총_교통수단_수'] / population_safe
    
    # 교통 부족 순위 (인구 대비 비율의 오름차순 랭킹: 비율이 낮을수록 1등)
    gdf['교통 부족 순위'] = gdf['인구 대비 교통수단 비율'].rank(ascending=True, method='min')

    return gdf, df_stations

# --------------------------------------------------------------------------
# 3. 화면 구성 및 시각화
# --------------------------------------------------------------------------
result = load_and_merge_data()

if result is None or result[0] is None:
    st.error("데이터 로드 중 문제가 발생했습니다.")
    st.stop()

gdf, df_stations = result

st.sidebar.header("🔍 분석 옵션")

# [요청하신 순서]
metrics_order = [
    ('상주 인구', '총_상주인구_수'),
    ('인구 밀도', '인구 밀도'),
    ('집객시설 수', '집객시설_수'),
    ('버스정류장 밀도', '버스정류장 밀도'),
    ('지하철역 밀도', '지하철역 밀도'),
    ('대중교통 밀도 (버스+지하철)', '대중교통 밀도'),
    ('교통 부족 순위 (인구 대비)', '교통 부족 순위')
]

valid_metrics = {}
for k, v in metrics_order:
    if v in gdf.columns:
        if gdf[v].sum() > 0 or '순위' in k:
            valid_metrics[k] = v

if valid_metrics:
    # 1. 지표 선택
    selected_name = st.sidebar.radio("분석할 지표 선택", list(valid_metrics.keys()))
    selected_col = valid_metrics[selected_name]
    
    st.sidebar.markdown("---")
    # 2. 개수 조절
    display_count = st.sidebar.slider("📊 그래프/표 표시 개수", 5, 25, 10)
    st.sidebar.markdown("---")
    # 3. 자치구 선택
    district_list = ['전체 서울시'] + sorted(gdf['자치구명'].unique().tolist())
    selected_district = st.sidebar.selectbox("자치구 상세 보기", district_list)

    # =================================================================
    # [레이아웃] 왼쪽: 지도 / 오른쪽: 그래프
    # =================================================================
  col_map, col_chart = st.columns([1, 1])

    # --- 색상 조건 설정 ---
    # 파란색 그룹: 인구, 수요 (값이 클수록 진하게)
    if selected_col in ['총_상주인구_수', '인구 밀도', '집객시설 수']:
        colorscale = 'Blues'
    # 빨간색 그룹: 인프라, 밀도, 순위 (값이 클수록 진하게)
    else:
        colorscale = 'Reds'

    # ----------------------------------------
    # [왼쪽] 지도
    # ----------------------------------------
    with col_map:
        st.subheader(f"🗺️ 서울시 {selected_name} 지도")
        
        center_lat, center_lon, zoom = 37.5665, 126.9780, 9.5
        map_data = gdf.copy()

        if selected_district != '전체 서울시':
            map_data = gdf[gdf['자치구명'] == selected_district]
            center_lat = map_data.geometry.centroid.y.values[0]
            center_lon = map_data.geometry.centroid.x.values[0]
            zoom = 11.0

        fig_map = px.choropleth_mapbox(
            map_data, 
            geojson=map_data.geometry.__geo_interface__, 
            locations=map_data.index,
            color=selected_col, 
            mapbox_style="carto-positron", 
            zoom=zoom,
            center={"lat": center_lat, "lon": center_lon}, 
            opacity=0.7, # 불투명도 약간 높임
            hover_name='자치구명', 
            hover_data=[selected_col], 
            color_continuous_scale=colorscale
        )
        
        fig_map.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=500)
        st.plotly_chart(fig_map, use_container_width=True)

    # ----------------------------------------
    # [오른쪽] 막대 그래프
    # ----------------------------------------
    with col_chart:
        st.subheader(f"📊 {selected_name} 순위 비교")
        
        sort_opt = st.radio("정렬 기준:", ["상위", "하위"], horizontal=True, key="sort_chart")
        
        # 순위/밀도가 높을수록 (큰 값) 상위 정렬
        df_sorted = gdf.sort_values(by=selected_col, ascending=False).head(display_count)
        if sort_opt == "하위":
             df_sorted = gdf.sort_values(by=selected_col, ascending=True).head(display_count)
        
        # 선택된 자치구 강조 (빨간색)
        df_sorted['color'] = df_sorted['자치구명'].apply(lambda x: '#FF4B4B' if x == selected_district else '#8884d8')
        
        fig_bar = px.bar(
            df_sorted, x='자치구명', y=selected_col, 
            text=selected_col, color='color', color_discrete_map='identity'
        )
        
        fmt = '%{text:.0f}' if '순위' in selected_name or '인구' in selected_name else '%{text:.4f}'
        fig_bar.update_traces(texttemplate=fmt, textposition='outside')
        fig_bar.update_layout(
            showlegend=False, 
            xaxis_title=None, 
            height=500,
            margin={"r":0,"t":20,"l":0,"b":0}
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # ----------------------------------------
    # [하단] 상세 데이터 표
    # ----------------------------------------
    st.markdown("---")
    st.subheader("📋 상세 데이터 표")
    cols_to_show = ['자치구명'] + list(valid_metrics.values())
    
    # 표도 정렬 옵션에 맞춰서 보여줌
    df_table = gdf[cols_to_show].sort_values(by=selected_col, ascending=(sort_opt=="하위")).head(display_count)
    st.dataframe(df_table, use_container_width=True, hide_index=True)
    
    csv = gdf[cols_to_show].to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 전체 데이터 다운로드 (CSV)", csv, "seoul_analysis.csv", "text/csv")
