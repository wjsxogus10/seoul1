import streamlit as st
import pandas as pd
import geopandas
import plotly.express as px
import plotly.graph_objects as go
import os
from shapely.geometry import Point

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
    # [A] 지도 데이터 로드
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

    # [B] 사용자 데이터 병합
    
    # 컬럼 초기화
    cols_init = ['총_상주인구_수', '인구 밀도', '집객시설 수', '버스정류장_수', '버스정류장 밀도', '지하철역_수', '지하철역 밀도']
    for c in cols_init:
        if c not in gdf.columns:
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

    # 3. 버스정류장
    try:
        df_bus = pd.read_excel('./data/GGD_StationInfo_M.xlsx').dropna(subset=['X', 'Y'])
        geom = [Point(xy) for xy in zip(df_bus['X'], df_bus['Y'])]
        gdf_bus = geopandas.GeoDataFrame(df_bus, geometry=geom, crs="EPSG:4326")
        joined = geopandas.sjoin(gdf_bus, gdf, how="inner", predicate="within")
        cnt = joined.groupby('자치구명').size().reset_index(name='버스정류장_수')
        
        gdf = gdf.drop(columns=['버스정류장_수', '버스정류장 밀도'], errors='ignore')
        gdf = gdf.merge(cnt, on='자치구명', how='left')
        gdf['버스정류장_수'] = gdf['버스정류장_수'].fillna(0)
        gdf['버스정류장 밀도'] = gdf['버스정류장_수'] / gdf['면적(km²)']
    except: pass

    # 4. 지하철 밀도 (사용자 지정 로직 유지)
    density_file = './data/지하철 밀도.CSV'
    if os.path.exists(density_file):
        try:
            try: df_dens = pd.read_csv(density_file, encoding='utf-8')
            except: df_dens = pd.read_csv(density_file, encoding='cp949')
            
            gu_col = next((c for c in df_dens.columns if '자치구' in c), None)
            dens_col = next((c for c in df_dens.columns if '밀도' in c), None)
            cnt_col = next((c for c in df_dens.columns if '역' in c and '수' in c), None)
            
            if gu_col and dens_col:
                rename_map_sub = {gu_col: '자치구명', dens_col: '지하철역 밀도'}
                if cnt_col:
                    rename_map_sub[cnt_col] = '지하철역_수'

                df_dens = df_dens.rename(columns=rename_map_sub)
                
                gdf = gdf.drop(columns=['지하철역 밀도', '지하철역_수'], errors='ignore')
                gdf = gdf.merge(df_dens[['자치구명', '지하철역 밀도', '지하철역_수']], on='자치구명', how='left')
                gdf['지하철역 밀도'] = gdf['지하철역 밀도'].fillna(0)
                gdf['지하철역_수'] = gdf['지하철역_수'].fillna(0)
        except: pass

    # 5. 통계 계산
    gdf['총_교통수단_수'] = gdf.get('버스정류장_수', 0) + gdf.get('지하철역_수', 0)
    gdf['대중교통 밀도 (면적당)'] = gdf['총_교통수단_수'] / gdf['면적(km²)']
    
    population_safe = gdf['총_상주인구_수'].replace(0, 1)
    gdf['인구 대비 교통수단 비율'] = gdf['총_교통수단_수'] / population_safe
    gdf['교통 부족 순위 (인구 대비)'] = gdf['인구 대비 교통수단 비율'].rank(ascending=True, method='min')

    # ----------------------------------------------------------------------
    # [핵심] 컬럼명에 단위 추가 (화면에 깔끔하게 표시하기 위함)
    # ----------------------------------------------------------------------
    rename_units = {
        '총_상주인구_수': '총 상주인구 수 (명)',
        '인구 밀도': '인구 밀도 (명/km²)',
        '집객시설 수': '집객시설 수 (개)',
        '버스정류장_수': '버스정류장 수 (개)',
        '버스정류장 밀도': '버스정류장 밀도 (개/km²)',
        '지하철역_수': '지하철역 수 (개)',
        '지하철역 밀도': '지하철역 밀도 (개/km²)',
        '대중교통 밀도 (면적당)': '대중교통 밀도 (개/km²)',
        '인구 대비 교통수단 비율': '인구 대비 교통수단 비율 (개/명)',
        '교통 부족 순위 (인구 대비)': '교통 부족 순위 (위)'
    }
    # 존재하는 컬럼만 변경
    gdf = gdf.rename(columns={k: v for k, v in rename_units.items() if k in gdf.columns})

    return gdf



# --------------------------------------------------------------------------
# 3. 화면 구성 및 시각화
# --------------------------------------------------------------------------
gdf = load_and_merge_data()

if gdf is None:
    st.error("데이터 로드 중 문제가 발생했습니다.")
    st.stop()

st.sidebar.header("🔍 분석 옵션")

# 분석 가능한 지표 (단위가 포함된 새 이름으로 리스트업)
metrics_order = [
    '총 상주인구 수 (명)',
    '인구 밀도 (명/km²)',
    '집객시설 수 (개)',
    '버스정류장 밀도 (개/km²)',
    '지하철역 밀도 (개/km²)',
    '대중교통 밀도 (개/km²)',
    '인구 대비 교통수단 비율 (개/명)',
    '교통 부족 순위 (위)'
]

# 실제 데이터에 존재하는 컬럼만 필터링
valid_metrics = [m for m in metrics_order if m in gdf.columns]

if valid_metrics:
    # 1. 지표 선택
    selected_col = st.sidebar.radio("분석할 지표 선택", valid_metrics)
    
    st.sidebar.markdown("---")
    # 2. 개수 조절
    display_count = st.sidebar.slider("📊 그래프/표 표시 개수", 5, 25, 10)
    st.sidebar.markdown("---")
    # 3. 자치구 선택
    district_list = ['전체 서울시'] + sorted(gdf['자치구명'].unique().tolist())
    selected_district = st.sidebar.selectbox("자치구 상세 보기", district_list)

    # 레이아웃
    col_map, col_chart = st.columns([1, 1])

    # [지도]
    with col_map:
        st.subheader(f"🗺️ 서울시 {selected_col} 지도")
        
        center_lat, center_lon, zoom = 37.5665, 126.9780, 9.5
        map_data = gdf.copy()

        if selected_district != '전체 서울시':
            map_data = gdf[gdf['자치구명'] == selected_district]
            center_lat = map_data.geometry.centroid.y.values[0]
            center_lon = map_data.geometry.centroid.x.values[0]
            zoom = 11.0

        colorscale = 'Reds_r' if '부족' in selected_col else 'YlGnBu'

        fig = px.choropleth_mapbox(
            map_data, 
            geojson=map_data.geometry.__geo_interface__, 
            locations=map_data.index,
            color=selected_col, 
            mapbox_style="carto-positron", 
            zoom=zoom,
            center={"lat": center_lat, "lon": center_lon}, 
            opacity=0.6,
            hover_name='자치구명', 
            hover_data=[selected_col], 
            color_continuous_scale=colorscale
        )
        fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=500)
        st.plotly_chart(fig, use_container_width=True)

    # [그래프]
    with col_chart:
        st.subheader(f"📊 {selected_col} 순위 비교")
        
        sort_opt = st.radio("정렬 기준:", ["상위", "하위"], horizontal=True, key="sort_chart")
        
        if sort_opt == "상위":
            df_sorted = gdf.sort_values(by=selected_col, ascending=False).head(display_count)
        else:
            df_sorted = gdf.sort_values(by=selected_col, ascending=True).head(display_count)
            
        df_sorted['color'] = df_sorted['자치구명'].apply(lambda x: '#FF4B4B' if x == selected_district else '#8884d8')
        
        fig_bar = px.bar(
            df_sorted, x='자치구명', y=selected_col, 
            text=selected_col, color='color', color_discrete_map='identity'
        )
        
        # 단위에 따른 숫자 포맷 (정수 vs 소수)
        fmt = '%{text:,.0f}' if '명)' in selected_col or '개)' in selected_col or '위)' in selected_col else '%{text:,.4f}'
        
        fig_bar.update_traces(texttemplate=fmt, textposition='outside')
        fig_bar.update_layout(
            showlegend=False, 
            xaxis_title=None, 
            height=500,
            margin={"r":0,"t":20,"l":0,"b":0}
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # [표] 인덱스 숨기기 및 다운로드
    st.markdown("---")
    st.subheader("📋 상세 데이터 표")
    cols_to_show = ['자치구명'] + valid_metrics
    
    # 정렬 (부족 순위는 오름차순이 '나쁜' 것이므로 로직 조정)
    is_ascending = (sort_opt == "하위") or ('부족' in selected_col and sort_opt == "상위")
    if '부족' in selected_col and sort_opt == "상위": is_ascending = True # 부족 순위 1위가 상위(가장 부족)
    
    df_table = gdf[cols_to_show].sort_values(by=selected_col, ascending=(sort_opt == "하위")).head(display_count)
    
    # 인덱스 숨기기 (hide_index=True)
    st.dataframe(df_table, use_container_width=True, hide_index=True)
    
    csv = gdf[cols_to_show].to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 전체 데이터 다운로드 (CSV)", csv, "seoul_analysis.csv", "text/csv")
