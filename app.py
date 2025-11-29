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
# 2. 데이터 로드 및 병합 함수 (Smart Detection)
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
        else: return None, None
            
        gdf['면적(km²)'] = gdf.geometry.to_crs(epsg=5179).area / 1_000_000
    except Exception as e:
        st.error(f"❌ 지도 로드 실패: {e}")
        return None, None

    # (B) 데이터 병합
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
        path = './data/서울시 상권분석서비스(집객시설-자치구).csv'
        if os.path.exists(path):
            df = pd.read_csv(path, encoding='cp949')
            val_col = next((c for c in df.columns if '집객' in c or '시설' in c), None)
            gu_col = next((c for c in df.columns if '자치구' in c), None)
            if val_col and gu_col:
                grp = df.groupby(gu_col)[val_col].mean().reset_index().rename(columns={gu_col:'자치구명', val_col:'집객시설 수'})
                gdf = gdf.merge(grp, on='자치구명', how='left', suffixes=('', '_new'))
                if '집객시설 수_new' in gdf.columns:
                    gdf['집객시설 수'] = gdf['집객시설 수_new'].fillna(0)
    except: pass

    # 3. [수정됨] 버스정류장 밀도 (지능형 좌표계 탐지)
    try:
        bus_path = './data/GGD_StationInfo_M.xlsx'
        if os.path.exists(bus_path):
            df_bus = pd.read_excel(bus_path).dropna(subset=['X', 'Y'])
            
            # 한국에서 자주 쓰이는 좌표계 3개를 다 시도해봅니다.
            # 5181: 중부원점 (카카오 등), 5179: UTM-K (네이버 등), 4326: 위경도
            crs_candidates = ['EPSG:5181', 'EPSG:5179', 'EPSG:4326']
            success = False
            
            for crs_code in crs_candidates:
                try:
                    geom = [Point(xy) for xy in zip(df_bus['X'], df_bus['Y'])]
                    gdf_bus = geopandas.GeoDataFrame(df_bus, geometry=geom, crs=crs_code)
                    
                    if crs_code != 'EPSG:4326':
                        gdf_bus = gdf_bus.to_crs(epsg=4326)
                    
                    # 서울 지도 안에 들어오는 점이 있는지 확인 (Spatial Join)
                    joined = geopandas.sjoin(gdf_bus, gdf[['자치구명', 'geometry']], how="inner", predicate="within")
                    
                    if not joined.empty:
                        # 성공하면 바로 집계
                        cnt = joined.groupby('자치구명').size().reset_index(name='버스정류장_수')
                        gdf = gdf.merge(cnt, on='자치구명', how='left')
                        gdf['버스정류장_수'] = gdf['버스정류장_수'].fillna(0)
                        gdf['버스정류장 밀도'] = gdf['버스정류장_수'] / gdf['면적(km²)']
                        success = True
                        # st.sidebar.success(f"버스 좌표계 찾음: {crs_code}") # 디버깅용
                        break
                except:
                    continue
            
            if not success:
                st.sidebar.warning("⚠️ 버스 파일은 있지만 좌표가 서울 밖입니다.")
    except Exception as e: 
        st.sidebar.error(f"버스 데이터 에러: {e}")

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
                gdf = gdf.merge(df_dens[['자치구명', '지하철역 밀도', '지하철역_수']], on='자치구명', how='left')
                
                # 병합 후 처리 (중복 컬럼 방지)
                if '지하철역 밀도_y' in gdf.columns:
                    gdf['지하철역 밀도'] = gdf['지하철역 밀도_y'].fillna(0)
                else:
                    gdf['지하철역 밀도'] = gdf['지하철역 밀도'].fillna(0)
                    
                if '지하철역_수_y' in gdf.columns:
                    gdf['지하철역_수'] = gdf['지하철역_수_y'].fillna(0)
                else:
                    gdf['지하철역_수'] = gdf['지하철역_수'].fillna(0)
        except: pass

    # 5. 지하철 좌표
    df_stations = pd.DataFrame()
    try:
        coord_file = './data/지하철 위경도.CSV'
        if os.path.exists(coord_file):
            try: df_stations = pd.read_csv(coord_file, encoding='utf-8')
            except: df_stations = pd.read_csv(coord_file, encoding='cp949')
            x_col = next((c for c in df_stations.columns if c in ['point_x', '경도', 'lon']), None)
            y_col = next((c for c in df_stations.columns if c in ['point_y', '위도', 'lat']), None)
            if x_col and y_col:
                df_stations = df_stations.rename(columns={x_col:'point_x', y_col:'point_y'})
    except: pass

    # 6. 계산
    gdf['총_교통수단_수'] = gdf['버스정류장_수'] + gdf['지하철역_수']
    gdf['대중교통 밀도'] = gdf['총_교통수단_수'] / gdf['면적(km²)']
    
    pop_safe = gdf['총_상주인구_수'].replace(0, 1)
    gdf['인구 대비 교통수단 비율'] = gdf['총_교통수단_수'] / pop_safe
    gdf['교통 부족 순위'] = gdf['인구 대비 교통수단 비율'].rank(ascending=True, method='min')

    return gdf, df_stations

# --------------------------------------------------------------------------
# 3. 화면 구성
# --------------------------------------------------------------------------
result = load_and_merge_data()
if result is None or result[0] is None:
    st.error("데이터 로드 중 오류가 발생했습니다.")
    st.stop()

gdf, df_stations = result

st.sidebar.header("🔍 분석 옵션")

metrics_order = [
    ('상주 인구', '총_상주인구_수'),
    ('인구 밀도', '인구 밀도'),
    ('집객시설 수', '집객시설 수'),
    ('버스정류장 밀도', '버스정류장 밀도'),
    ('지하철역 밀도', '지하철역 밀도'),
    ('대중교통 밀도 (버스+지하철)', '대중교통 밀도'),
    ('교통 부족 순위 (인구 대비)', '교통 부족 순위')
]

valid_metrics = {}
for k, v in metrics_order:
    if v in gdf.columns:
        valid_metrics[k] = v

if not valid_metrics:
    st.error("데이터가 없습니다.")
    st.stop()

selected_name = st.sidebar.radio("분석할 지표 선택", list(valid_metrics.keys()))
selected_col = valid_metrics[selected_name]

st.sidebar.markdown("---")
display_count = st.sidebar.slider("📊 그래프/표 표시 개수", 5, 25, 10)
st.sidebar.markdown("---")
district_list = ['전체 서울시'] + sorted(gdf['자치구명'].astype(str).unique().tolist())
selected_district = st.sidebar.selectbox("자치구 상세 보기", district_list)

# 색상
colorscale = 'Blues' if selected_col in ['총_상주인구_수', '인구 밀도', '집객시설 수'] else 'Reds'

col_map, col_chart = st.columns([1, 1])

with col_map:
    st.subheader(f"🗺️ 서울시 {selected_name} 지도")
    center_lat, center_lon, zoom = 37.5665, 126.9780, 9.5
    map_data = gdf.copy()

    if selected_district != '전체 서울시':
        map_data = gdf[gdf['자치구명'] == selected_district]
        try:
            center_lat = map_data.geometry.centroid.y.values[0]
            center_lon = map_data.geometry.centroid.x.values[0]
            zoom = 11.0
        except: pass

    fig_map = px.choropleth_mapbox(
        map_data, 
        geojson=map_data.geometry.__geo_interface__, 
        locations=map_data.index,
        color=selected_col, 
        mapbox_style="carto-positron", 
        zoom=zoom, 
        center={"lat": center_lat, "lon": center_lon}, 
        opacity=0.7,
        hover_name='자치구명', 
        hover_data=[selected_col], 
        color_continuous_scale=colorscale
    )
    
    if ('지하철' in selected_name or '대중교통' in selected_name) and not df_stations.empty:
        if 'point_x' in df_stations.columns:
            fig_map.add_trace(go.Scattermapbox(
                lat=df_stations['point_y'], lon=df_stations['point_x'],
                mode='markers', marker=go.scattermapbox.Marker(size=5, color='red'),
                name='역 위치'
            ))

    fig_map.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=500)
    st.plotly_chart(fig_map, use_container_width=True)

with col_chart:
    st.subheader(f"📊 {selected_name} 순위 비교")
    sort_opt = st.radio("정렬 기준:", ["상위", "하위"], horizontal=True, key="chart_sort")
    ascending = True if sort_opt == "하위" else False
    
    df_sorted = gdf.sort_values(by=selected_col, ascending=ascending).head(display_count)
    df_sorted['color'] = df_sorted['자치구명'].apply(lambda x: '#FF4B4B' if x == selected_district else '#8884d8')
    
    fig_bar = px.bar(
        df_sorted, x='자치구명', y=selected_col, 
        text=selected_col, color='color', color_discrete_map='identity'
    )
    
    fmt = '%{text:.0f}' if '순위' in selected_name or '인구' in selected_name else '%{text:.2f}'
    fig_bar.update_traces(texttemplate=fmt, textposition='outside')
    fig_bar.update_layout(showlegend=False, xaxis_title=None, height=500, margin={"r":0,"t":20,"l":0,"b":0})
    st.plotly_chart(fig_bar, use_container_width=True)

st.markdown("---")
st.subheader("📋 상세 데이터 표")
cols_to_show = ['자치구명'] + list(valid_metrics.values())
cols_to_show = list(dict.fromkeys(cols_to_show))
cols_to_show = [c for c in cols_to_show if c in gdf.columns]

df_table = gdf[cols_to_show].sort_values(by=selected_col, ascending=(sort_opt=="하위")).head(display_count)
st.dataframe(df_table, use_container_width=True, hide_index=True)

csv = gdf[cols_to_show].to_csv(index=False).encode('utf-8-sig')
st.download_button("📥 전체 데이터 다운로드 (CSV)", csv, "seoul_analysis.csv", "text/csv")
