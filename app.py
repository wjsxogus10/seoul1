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

    # (B) 사용자 데이터 병합
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
        val_col = next((c for c in df.columns if '집객' in c or '시설' in c), None)
        gu_col = next((c for c in df.columns if '자치구' in c), None)
        if val_col and gu_col:
            grp = df.groupby(gu_col)[val_col].mean().reset_index().rename(columns={gu_col:'자치구명', val_col:'집객시설 수'})
            gdf = gdf.merge(grp, on='자치구명', how='left', suffixes=('', '_new'))
            if '집객시설 수_new' in gdf.columns:
                gdf['집객시설 수'] = gdf['집객시설 수_new'].fillna(0)
    except: pass

    # 3. [강화됨] 버스 정류장 (좌표 보정 및 점 찍기 데이터 생성)
    df_bus_stations = pd.DataFrame()
    try:
        bus_path = './data/GGD_StationInfo_M.xlsx'
        if os.path.exists(bus_path):
            df_bus = pd.read_excel(bus_path).dropna(subset=['X', 'Y'])
            
            # 좌표계 후보군 (5181, 5179, 4326) + X,Y 반전 시도
            crs_list = ['EPSG:5181', 'EPSG:5179', 'EPSG:4326']
            success = False
            
            for crs_code in crs_list:
                # Case 1: 정상 순서 (X, Y)
                try:
                    geom = [Point(xy) for xy in zip(df_bus['X'], df_bus['Y'])]
                    gdf_bus = geopandas.GeoDataFrame(df_bus, geometry=geom, crs=crs_code)
                    if crs_code != 'EPSG:4326': gdf_bus = gdf_bus.to_crs(epsg=4326)
                    
                    joined = geopandas.sjoin(gdf_bus, gdf[['자치구명', 'geometry']], how="inner", predicate="within")
                    if not joined.empty:
                        success = True
                        df_bus_stations = joined.copy() # 시각화용 저장
                        df_bus_stations['point_x'] = df_bus_stations.geometry.x
                        df_bus_stations['point_y'] = df_bus_stations.geometry.y
                        break
                except: pass
                
                # Case 2: 좌표 반전 (Y, X) - 가끔 엑셀 파일이 반대로 되어있음
                try:
                    geom = [Point(xy) for xy in zip(df_bus['Y'], df_bus['X'])]
                    gdf_bus = geopandas.GeoDataFrame(df_bus, geometry=geom, crs=crs_code)
                    if crs_code != 'EPSG:4326': gdf_bus = gdf_bus.to_crs(epsg=4326)
                    
                    joined = geopandas.sjoin(gdf_bus, gdf[['자치구명', 'geometry']], how="inner", predicate="within")
                    if not joined.empty:
                        success = True
                        df_bus_stations = joined.copy()
                        df_bus_stations['point_x'] = df_bus_stations.geometry.x
                        df_bus_stations['point_y'] = df_bus_stations.geometry.y
                        break
                except: pass
                
                if success: break
            
            if success:
                cnt = df_bus_stations.groupby('자치구명').size().reset_index(name='버스정류장_수')
                gdf = gdf.merge(cnt, on='자치구명', how='left')
                if '버스정류장_수_y' in gdf.columns:
                    gdf['버스정류장_수'] = gdf['버스정류장_수_y'].fillna(0)
                gdf['버스정류장 밀도'] = gdf['버스정류장_수'] / gdf['면적(km²)']
                # st.sidebar.success("✅ 버스 정류장 데이터 로드 성공!")
            else:
                st.sidebar.warning("⚠️ 버스 좌표가 서울 지도와 맞지 않습니다.")
    except Exception as e: 
        st.sidebar.error(f"버스 데이터 에러: {e}")

    # 4. 지하철 밀도
    try:
        path = './data/지하철 밀도.CSV'
        if os.path.exists(path):
            try: df_dens = pd.read_csv(path, encoding='utf-8')
            except: df_dens = pd.read_csv(path, encoding='cp949')
            
            gu = next((c for c in df_dens.columns if '자치구' in c), None)
            den = next((c for c in df_dens.columns if '밀도' in c), None)
            cnt = next((c for c in df_dens.columns if '역' in c and '수' in c), None)
            
            if gu and den:
                rename_map = {gu: '자치구명', den: '지하철역 밀도'}
                if cnt: rename_map[cnt] = '지하철역_수'
                df_dens = df_dens.rename(columns=rename_map)
                
                cols = ['자치구명', '지하철역 밀도']
                if '지하철역_수' in df_dens.columns: cols.append('지하철역_수')
                
                gdf = gdf.merge(df_dens[cols], on='자치구명', how='left', suffixes=('', '_sub'))
                if '지하철역 밀도_sub' in gdf.columns: gdf['지하철역 밀도'] = gdf['지하철역 밀도_sub'].fillna(0)
                if '지하철역_수_sub' in gdf.columns: gdf['지하철역_수'] = gdf['지하철역_수_sub'].fillna(0)
    except: pass

    # 5. 지하철 좌표
    df_stations = pd.DataFrame()
    try:
        path = './data/지하철 위경도.CSV'
        if os.path.exists(path):
            try: df_stations = pd.read_csv(path, encoding='utf-8')
            except: df_stations = pd.read_csv(path, encoding='cp949')
            x = next((c for c in df_stations.columns if c in ['point_x', '경도', 'lon']), None)
            y = next((c for c in df_stations.columns if c in ['point_y', '위도', 'lat']), None)
            if x and y:
                df_stations = df_stations.rename(columns={x:'point_x', y:'point_y'})
    except: pass

    # 6. 계산
    gdf['총_교통수단_수'] = gdf['버스정류장_수'].fillna(0) + gdf['지하철역_수'].fillna(0)
    gdf['대중교통 밀도'] = gdf['총_교통수단_수'] / gdf['면적(km²)']
    
    pop_safe = gdf['총_상주인구_수'].replace(0, 1)
    gdf['인구 대비 교통수단 비율'] = gdf['총_교통수단_수'] / pop_safe
    gdf['교통 부족 순위'] = gdf['인구 대비 교통수단 비율'].rank(ascending=True, method='min')

    return gdf, df_stations, df_bus_stations

# --------------------------------------------------------------------------
# 3. 화면 구성
# --------------------------------------------------------------------------
result = load_and_merge_data()
if result is None or result[0] is None:
    st.error("데이터 로드 실패")
    st.stop()

gdf, df_stations, df_bus_stations = result

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
    if v in gdf.columns: valid_metrics[k] = v

if not valid_metrics:
    st.error("표시할 데이터가 없습니다.")
    st.stop()

selected_name = st.sidebar.radio("분석할 지표 선택", list(valid_metrics.keys()))
selected_col = valid_metrics[selected_name]

st.sidebar.markdown("---")
display_count = st.sidebar.slider("📊 그래프/표 표시 개수", 5, 25, 10)
st.sidebar.markdown("---")
district_list = ['전체 서울시'] + sorted(gdf['자치구명'].unique().tolist())
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
    
    # [점 찍기 로직]
    # 1. 지하철 관련 지표일 때 -> 지하철역 표시
    if ('지하철' in selected_name) and not df_stations.empty:
        if 'point_x' in df_stations.columns:
            fig_map.add_trace(go.Scattermapbox(
                lat=df_stations['point_y'], lon=df_stations['point_x'],
                mode='markers', marker=go.scattermapbox.Marker(size=5, color='red'),
                name='지하철역'
            ))
            
    # 2. 버스 관련 지표일 때 -> 버스정류장 표시 (NEW)
    if ('버스' in selected_name) and not df_bus_stations.empty:
        # 데이터가 너무 많으면 느려질 수 있으므로, 선택된 구가 있으면 그 구만, 아니면 전체 표시
        bus_points = df_bus_stations
        if selected_district != '전체 서울시':
            bus_points = df_bus_stations[df_bus_stations['자치구명'] == selected_district]
        
        if not bus_points.empty:
            fig_map.add_trace(go.Scattermapbox(
                lat=bus_points['point_y'], lon=bus_points['point_x'],
                mode='markers', marker=go.scattermapbox.Marker(size=3, color='blue'),
                name='버스정류장'
            ))
            
    # 3. 대중교통/교통부족일 때 -> 둘 다 표시 (선택된 구만)
    if ('대중교통' in selected_name or '부족' in selected_name) and selected_district != '전체 서울시':
         if not df_stations.empty:
             # 지하철은 구별 데이터가 없어서 전체 표시되지만 개수가 적어서 괜찮음
             fig_map.add_trace(go.Scattermapbox(
                lat=df_stations['point_y'], lon=df_stations['point_x'],
                mode='markers', marker=go.scattermapbox.Marker(size=5, color='red'),
                name='지하철역'
            ))
         if not df_bus_stations.empty:
             bus_points = df_bus_stations[df_bus_stations['자치구명'] == selected_district]
             fig_map.add_trace(go.Scattermapbox(
                lat=bus_points['point_y'], lon=bus_points['point_x'],
                mode='markers', marker=go.scattermapbox.Marker(size=3, color='blue'),
                name='버스정류장'
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
