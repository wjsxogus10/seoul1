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
# 2. 데이터 로드 및 병합 함수
# --------------------------------------------------------------------------
@st.cache_data
def load_and_merge_data():
    # [A] 지도 데이터 로드
    map_url = "https://raw.githubusercontent.com/southkorea/seoul-maps/master/kostat/2013/json/seoul_municipalities_geo_simple.json"
    try:
        gdf = geopandas.read_file(map_url)
        gdf = gdf.to_crs(epsg=4326)
        
        if 'name' in gdf.columns: gdf = gdf.rename(columns={'name': '자치구명'})
        elif 'SIG_KOR_NM' in gdf.columns: gdf = gdf.rename(columns={'SIG_KOR_NM': '자치구명'})
            
        gdf_area = gdf.to_crs(epsg=5179)
        gdf['면적(km²)'] = gdf_area.geometry.area / 1_000_000
    except Exception as e:
        st.error(f"지도 로드 실패: {e}")
        return None

    # [B] 사용자 데이터 병합
    cols_init = ['총_상주인구_수', '인구 밀도', '집객시설 수', '버스정류장_수', '버스정류장 밀도', '지하철역_수', '지하철역 밀도']
    for c in cols_init: gdf[c] = 0

    # 1. 인구
    try:
        df_pop = pd.read_csv('./data/서울시 상권분석서비스(상주인구-자치구).csv', encoding='cp949')
        grp = df_pop.groupby('자치구_코드_명')['총_상주인구_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.drop(columns=['총_상주인구_수', '인구 밀도'], errors='ignore')
        gdf = gdf.merge(grp, on='자치구명', how='left')
        gdf['총_상주인구_수'] = gdf['총_상주인구_수'].fillna(0)
        gdf['인구 밀도'] = gdf['총_상주인구_수'] / gdf['면적(km²)']
    except: pass

    # 2. 상권
    try:
        df_biz = pd.read_csv('./data/서울시 상권분석서비스(집객시설-자치구).csv', encoding='cp949')
        grp = df_biz.groupby('자치구_코드_명')['집객시설_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.drop(columns=['집객시설 수'], errors='ignore')
        gdf = gdf.merge(grp, on='자치구명', how='left')
        gdf['집객시설 수'] = gdf['집객시설_수'].fillna(0)
    except: pass

    # 3. 버스 (엔진 지정)
    try:
        df_bus = pd.read_excel('./data/GGD_StationInfo_M.xlsx', engine='openpyxl').dropna(subset=['X', 'Y'])
        geom = [Point(xy) for xy in zip(df_bus['X'], df_bus['Y'])]
        gdf_bus = geopandas.GeoDataFrame(df_bus, geometry=geom, crs="EPSG:4326")
        joined = geopandas.sjoin(gdf_bus, gdf, how="inner", predicate="within")
        cnt = joined.groupby('자치구명').size().reset_index(name='버스정류장_수')
        
        gdf = gdf.drop(columns=['버스정류장_수', '버스정류장 밀도'], errors='ignore')
        gdf = gdf.merge(cnt, on='자치구명', how='left')
        gdf['버스정류장_수'] = gdf['버스정류장_수'].fillna(0)
        gdf['버스정류장 밀도'] = gdf['버스정류장_수'] / gdf['면적(km²)']
    except: pass

    # 4. 지하철 (에러 수정됨: engine='openpyxl' 추가)
    subway_files = [f for f in os.listdir('./data') if 'subway' in f.lower() or '지하철' in f]
    if subway_files:
        try:
            f_path = os.path.join('./data', subway_files[0])
            
            # CSV면 그냥 읽고, 아니면 엑셀로 간주하고 엔진 지정
            if f_path.lower().endswith('.csv'):
                try: df_sub = pd.read_csv(f_path, encoding='cp949')
                except: df_sub = pd.read_csv(f_path, encoding='utf-8')
            else:
                # [여기가 핵심 수정] engine='openpyxl'을 꼭 넣어야 함
                df_sub = pd.read_excel(f_path, engine='openpyxl')
            
            # 좌표 컬럼 찾기
            x_col = next((c for c in ['경도', 'X', 'lon', 'x'] if c in df_sub.columns), None)
            y_col = next((c for c in ['위도', 'Y', 'lat', 'y'] if c in df_sub.columns), None)

            if x_col and y_col:
                df_sub = df_sub.dropna(subset=[x_col, y_col])
                geom = [Point(xy) for xy in zip(df_sub[x_col], df_sub[y_col])]
                gdf_sub = geopandas.GeoDataFrame(df_sub, geometry=geom, crs="EPSG:4326")
                joined = geopandas.sjoin(gdf_sub, gdf, how="inner", predicate="within")
                cnt = joined.groupby('자치구명').size().reset_index(name='지하철역_수')
                
                gdf = gdf.drop(columns=['지하철역_수', '지하철역 밀도'], errors='ignore')
                gdf = gdf.merge(cnt, on='자치구명', how='left')
                gdf['지하철역_수'] = gdf['지하철역_수'].fillna(0)
                gdf['지하철역 밀도'] = gdf['지하철역_수'] / gdf['면적(km²)']
            else:
                st.error(f"⚠️ [지하철] 파일에 '경도/위도' 또는 'X/Y' 컬럼이 없습니다.")
        except Exception as e:
            st.error(f"⚠️ [지하철] 데이터 로드 실패: {e}")

    # 5. 통계 및 단위
    gdf['총_교통수단_수'] = gdf.get('버스정류장_수', 0) + gdf.get('지하철역_수', 0)
    gdf['대중교통 밀도 (면적당)'] = gdf['총_교통수단_수'] / gdf['면적(km²)']
    pop_safe = gdf['총_상주인구_수'].replace(0, 1)
    gdf['인구 대비 교통수단 비율'] = gdf['총_교통수단_수'] / pop_safe
    gdf['교통 부족 순위 (인구 대비)'] = gdf['인구 대비 교통수단 비율'].rank(ascending=True, method='min')

    rename_map = {
        '총_상주인구_수': '총 상주인구 수 (명)',
        '집객시설_수': '집객시설 수 (개)',
        '버스정류장_수': '버스정류장 수 (개)',
        '지하철역_수': '지하철역 수 (개)',
        '면적(km²)': '면적 (km²)',
        '인구 밀도': '인구 밀도 (명/km²)',
        '버스정류장 밀도': '버스정류장 밀도 (개/km²)',
        '지하철역 밀도': '지하철역 밀도 (개/km²)',
        '대중교통 밀도 (면적당)': '대중교통 밀도 (개/km²)',
        '인구 대비 교통수단 비율': '인구 대비 교통수단 비율 (개/명)',
        '교통 부족 순위 (인구 대비)': '교통 부족 순위 (위)'
    }
    gdf = gdf.rename(columns={k: v for k, v in rename_map.items() if k in gdf.columns})

    return gdf

# --------------------------------------------------------------------------
# 3. 화면 구성 및 시각화
# --------------------------------------------------------------------------
gdf = load_and_merge_data()

if gdf is not None:
    st.sidebar.header("🔍 분석 옵션")
    metrics_order = [
        '총 상주인구 수 (명)', '인구 밀도 (명/km²)', '집객시설 수 (개)',
        '버스정류장 밀도 (개/km²)', '지하철역 밀도 (개/km²)', '대중교통 밀도 (개/km²)',
        '인구 대비 교통수단 비율 (개/명)', '교통 부족 순위 (위)'
    ]
    valid_metrics = [m for m in metrics_order if m in gdf.columns]

    if valid_metrics:
        selected_col = st.sidebar.radio("분석할 지표 선택", valid_metrics)
        st.sidebar.markdown("---")
        display_count = st.sidebar.slider("📊 그래프/표 표시 개수", 5, 25, 10)
        st.sidebar.markdown("---")
        district_list = ['전체 서울시'] + sorted(gdf['자치구명'].unique().tolist())
        selected_district = st.sidebar.selectbox("자치구 상세 보기", district_list)

        col_map, col_chart = st.columns([1, 1])

        with col_map:
            st.subheader(f"🗺️ 서울시 {selected_col} 지도")
            center_lat, center_lon, zoom = 37.5665, 126.9780, 9.5
            map_data = gdf.copy()
            if selected_district != '전체 서울시':
                map_data = gdf[gdf['자치구명'] == selected_district]
                center_lat, center_lon = map_data.geometry.centroid.y.values[0], map_data.geometry.centroid.x.values[0]
                zoom = 11.0
            colorscale = 'Reds_r' if '부족' in selected_col else 'YlGnBu'
            
            fig = px.choropleth_mapbox(
                map_data, geojson=map_data.geometry.__geo_interface__, locations=map_data.index,
                color=selected_col, mapbox_style="carto-positron", zoom=zoom,
                center={"lat": center_lat, "lon": center_lon}, opacity=0.6,
                hover_name='자치구명', color_continuous_scale=colorscale
            )
            is_float = '밀도' in selected_col or '비율' in selected_col
            num_format = ",.4f" if is_float else ",.0f"
            fig.update_traces(hovertemplate=f"<b>%{{hovertext}}</b><br><br>{selected_col}: %{{z:{num_format}}}<extra></extra>")
            fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=500)
            st.plotly_chart(fig, use_container_width=True)

        with col_chart:
            st.subheader(f"📊 {selected_col} 순위 비교")
            avg_val = gdf[selected_col].mean()
            sort_opt = st.radio("정렬 기준:", ["상위", "하위"], horizontal=True, key="sort_chart")
            ascending = True if sort_opt == "하위" else False
            if '부족' in selected_col: ascending = not ascending
            df_sorted = gdf.sort_values(by=selected_col, ascending=ascending).head(display_count)
            df_sorted['color'] = df_sorted['자치구명'].apply(lambda x: '#FF4B4B' if x == selected_district else '#8884d8')
            
            fig_bar = px.bar(
                df_sorted, x='자치구명', y=selected_col, text=selected_col, 
                color='color', color_discrete_map='identity'
            )
            fig_bar.add_hline(y=avg_val, line_dash="dash", line_color="green", annotation_text=f"평균: {avg_val:,.2f}")
            fmt = '%{text:,.0f}' if '명)' in selected_col or '개)' in selected_col or '위)' in selected_col else '%{text:,.4f}'
            fig_bar.update_traces(texttemplate=fmt, textposition='outside')
            fig_bar.update_layout(showlegend=False, xaxis_title=None, height=500, margin={"r":0,"t":20,"l":0,"b":0})
            st.plotly_chart(fig_bar, use_container_width=True)

        st.markdown("---")
        st.subheader("📋 상세 데이터 표")
        cols_to_show = ['자치구명'] + valid_metrics
        df_table = gdf[cols_to_show].sort_values(by=selected_col, ascending=ascending).head(display_count)
        st.dataframe(df_table, use_container_width=True, hide_index=True)
        csv = gdf[cols_to_show].to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 전체 데이터 다운로드 (CSV)", csv, "seoul_analysis.csv", "text/csv")
    else:
        st.warning("분석할 데이터 파일이 없어 지도만 표시됩니다.")
