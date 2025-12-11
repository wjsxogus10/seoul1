import streamlit as st
import pandas as pd
import geopandas
import plotly.express as px
import os
from shapely.geometry import Point

# --------------------------------------------------------------------------
# 1. 페이지 설정
# --------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="서울시 도시계획 대시보드")
st.title("🏙️ 서울시 도시계획 및 대중교통 개선 대시보드")

# --------------------------------------------------------------------------
# 2. 데이터 로드 및 병합
# --------------------------------------------------------------------------
@st.cache_data
def load_and_merge_data():
    # (A) 지도 데이터 (인터넷 공공 데이터)
    map_url = "https://raw.githubusercontent.com/southkorea/seoul-maps/master/kostat/2013/json/seoul_municipalities_geo_simple.json"
    try:
        gdf = geopandas.read_file(map_url)
        gdf = gdf.to_crs(epsg=4326)
        
        col_map = {'name': '자치구명', 'SIG_KOR_NM': '자치구명'}
        gdf = gdf.rename(columns=col_map)
        
        gdf_area = gdf.to_crs(epsg=5179)
        gdf['면적(km²)'] = gdf_area.geometry.area / 1_000_000
    except Exception as e:
        st.error(f"지도 로드 실패: {e}")
        return None

    # (B) 사용자 데이터 병합
    # 1. 인구
    try:
        df_pop = pd.read_csv('./data/서울시 상권분석서비스(상주인구-자치구).csv', encoding='cp949')
        grp = df_pop.groupby('자치구_코드_명')['총_상주인구_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.merge(grp, on='자치구명', how='left')
        gdf['인구 밀도'] = gdf['총_상주인구_수'] / gdf['면적(km²)']
    except: pass

    # 2. 상권
    try:
        df_biz = pd.read_csv('./data/서울시 상권분석서비스(집객시설-자치구).csv', encoding='cp949')
        grp = df_biz.groupby('자치구_코드_명')['집객시설_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.merge(grp, on='자치구명', how='left')
    except: pass

    # 3. 버스
    try:
        df_bus = pd.read_excel('./data/GGD_StationInfo_M.xlsx').dropna(subset=['X', 'Y'])
        geom = [Point(xy) for xy in zip(df_bus['X'], df_bus['Y'])]
        gdf_bus = geopandas.GeoDataFrame(df_bus, geometry=geom, crs="EPSG:4326")
        joined = geopandas.sjoin(gdf_bus, gdf, how="inner", predicate="within")
        cnt = joined.groupby('자치구명').size().reset_index(name='버스정류장_수')
        gdf = gdf.merge(cnt, on='자치구명', how='left')
        gdf['버스정류장_수'] = gdf['버스정류장_수'].fillna(0)
        gdf['버스 밀도'] = gdf['버스정류장_수'] / gdf['면적(km²)']
    except: pass

    # 4. 지하철
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
                cnt = joined.groupby('자치구명').size().reset_index(name='지하철역_수')
                gdf = gdf.merge(cnt, on='자치구명', how='left')
                gdf['지하철역_수'] = gdf['지하철역_수'].fillna(0)
                gdf['지하철 밀도'] = gdf['지하철역_수'] / gdf['면적(km²)']
        except: pass
    else:
        gdf['지하철역_수'] = 0
        gdf['지하철 밀도'] = 0

    # -----------------------------------------------------------
    # [핵심] 컬럼명에 단위 추가 (사용자 요청 반영)
    # -----------------------------------------------------------
    rename_map = {
        '총_상주인구_수': '총 상주인구 수 (명)',
        '집객시설_수': '집객시설 수 (개)',
        '버스정류장_수': '버스정류장 수 (개)',
        '지하철역_수': '지하철역 수 (개)',
        '면적(km²)': '면적 (km²)',
        '인구 밀도': '인구 밀도 (명/km²)',
        '버스 밀도': '버스 밀도 (개/km²)',
        '지하철 밀도': '지하철 밀도 (개/km²)'
    }
    gdf = gdf.rename(columns=rename_map)
    
    # 교통 부족 순위 계산 (단위 붙은 이름 사용)
    if '버스정류장 수 (개)' in gdf.columns:
        gdf['총 정류장 수'] = gdf['버스정류장 수 (개)'] + gdf.get('지하철역 수 (개)', 0)
        gdf['교통 부족 순위 (위)'] = gdf['총 정류장 수'].rank(ascending=True, method='min')

    return gdf

# --------------------------------------------------------------------------
# 3. 화면 시각화
# --------------------------------------------------------------------------
gdf = load_and_merge_data()

if gdf is not None:
    st.sidebar.header("🔍 분석 옵션")
    
    # 분석 가능한 지표 (단위 포함된 이름)
    possible_metrics = [
        '인구 밀도 (명/km²)', 
        '버스 밀도 (개/km²)', 
        '지하철 밀도 (개/km²)', 
        '총 상주인구 수 (명)', 
        '집객시설 수 (개)', 
        '교통 부족 순위 (위)'
    ]
    valid_metrics = [m for m in possible_metrics if m in gdf.columns]
    
    if valid_metrics:
        # 1. 지표 선택
        selected_metric = st.sidebar.radio("분석할 지표", valid_metrics)
        st.sidebar.markdown("---")
        
        # 2. 자치구 선택
        district_list = ['전체 서울시'] + sorted(gdf['자치구명'].unique().tolist())
        selected_district = st.sidebar.selectbox("자치구 상세 보기", district_list)

        # =================================================================
        # [지도 + 그래프]
        # =================================================================
        col_map, col_chart = st.columns([1, 1])

        with col_map:
            st.subheader(f"🗺️ 서울시 {selected_metric} 지도")
            center_lat, center_lon, zoom = 37.5665, 126.9780, 9.5
            map_data = gdf.copy()
            
            if selected_district != '전체 서울시':
                map_data = gdf[gdf['자치구명'] == selected_district]
                center_lat = map_data.geometry.centroid.y.values[0]
                center_lon = map_data.geometry.centroid.x.values[0]
                zoom = 11.0

            colorscale = 'Reds_r' if '부족' in selected_metric else 'YlGnBu'
            
            fig = px.choropleth_mapbox(
                gdf, geojson=gdf.geometry.__geo_interface__, locations=gdf.index,
                color=selected_metric, mapbox_style="carto-positron", zoom=zoom,
                center={"lat": center_lat, "lon": center_lon}, opacity=0.6,
                hover_name='자치구명', hover_data=[selected_metric],
                color_continuous_scale=colorscale
            )
            fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=500)
            st.plotly_chart(fig, use_container_width=True)

        with col_chart:
            st.subheader(f"📊 {selected_metric} 순위")
            sort_opt = st.radio("정렬:", ["상위 10개", "하위 10개"], horizontal=True)
            
            if sort_opt == "상위 10개":
                df_sorted = gdf.sort_values(by=selected_metric, ascending=False).head(10)
            else:
                df_sorted = gdf.sort_values(by=selected_metric, ascending=True).head(10)
                
            df_sorted['color'] = df_sorted['자치구명'].apply(lambda x: '#FF4B4B' if x == selected_district else '#8884d8')
            
            fig_bar = px.bar(
                df_sorted, x='자치구명', y=selected_metric, 
                text=selected_metric, color='color', color_discrete_map='identity'
            )
            # 숫자 포맷 (정수/소수 구분)
            fmt = '%{text:,.0f}' if '명)' in selected_metric or '개)' in selected_metric or '위)' in selected_metric else '%{text:,.2f}'
            fig_bar.update_traces(texttemplate=fmt, textposition='outside')
            fig_bar.update_layout(showlegend=False, xaxis_title=None, height=500, margin={"r":0,"t":20,"l":0,"b":0})
            st.plotly_chart(fig_bar, use_container_width=True)

        # =================================================================
        # [표] 인덱스 숨기기 적용 (hide_index=True)
        # =================================================================
        st.markdown("---")
        st.subheader("📋 전체 데이터 상세 표")
        
        cols_to_show = ['자치구명'] + valid_metrics
        
        # [핵심] 여기서 hide_index=True를 써서 인덱스(0,1,2...)를 숨깁니다.
        st.dataframe(
            gdf[cols_to_show].sort_values(by=selected_metric, ascending=('위)' in selected_metric or '하위' in sort_opt)), 
            use_container_width=True, 
            hide_index=True
        )
        
        csv = gdf[cols_to_show].to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 엑셀(CSV) 다운로드", csv, "seoul_data.csv", "text/csv")

    else:
        st.warning("분석할 데이터 파일이 없어 지도만 표시됩니다.")
        st.info("data 폴더에 csv/xlsx 파일을 업로드하면 자동으로 분석됩니다.")
else:
    st.error("데이터를 로드하는 중 오류가 발생했습니다.")
