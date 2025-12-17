import streamlit as st
import pandas as pd
import geopandas
import plotly.express as px
import plotly.graph_objects as go
import os
from shapely.geometry import Point

# --------------------------------------------------------------------------
# 1. 페이지 설정
# --------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="서울시 도시계획 대시보드")

# --------------------------------------------------------------------------
# 2. 데이터 로드 및 병합 함수
# --------------------------------------------------------------------------
@st.cache_data
def load_and_merge_data():
    logs = []
    data_info = {} # 데이터 정보 저장

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

    # [B] 사용자 데이터 병합
    cols_init = ['총_상주인구_수', '인구 밀도', '집객시설 수', '버스정류장_수', '버스정류장 밀도', '지하철역_수', '지하철역 밀도', '총_교통수단_수']
    for c in cols_init: gdf[c] = 0

    # 1. 인구
    pop_file = '서울시 상권분석서비스(상주인구-자치구).csv'
    try:
        df_pop = pd.read_csv(f'./data/{pop_file}', encoding='cp949')
        grp = df_pop.groupby('자치구_코드_명')['총_상주인구_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.drop(columns=['총_상주인구_수', '인구 밀도'], errors='ignore')
        gdf = gdf.merge(grp, on='자치구명', how='left')
        gdf['총_상주인구_수'] = gdf['총_상주인구_수'].fillna(0)
        gdf['인구 밀도'] = gdf['총_상주인구_수'] / gdf['면적(km²)']
        data_info['인구'] = {'file': pop_file, 'status': '✅'}
    except: 
        data_info['인구'] = {'file': pop_file, 'status': '❌'}

    # 2. 상권
    biz_file = '서울시 상권분석서비스(집객시설-자치구).csv'
    try:
        df_biz = pd.read_csv(f'./data/{biz_file}', encoding='cp949')
        grp = df_biz.groupby('자치구_코드_명')['집객시설_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.drop(columns=['집객시설 수'], errors='ignore')
        gdf = gdf.merge(grp, on='자치구명', how='left')
        gdf['집객시설 수'] = gdf['집객시설_수'].fillna(0)
        data_info['상권'] = {'file': biz_file, 'status': '✅'}
    except:
        data_info['상권'] = {'file': biz_file, 'status': '❌'}

    # 3. 버스
    target_bus_file = "20250930기준_서울시정류소(정류소별).xlsx - 시내버스 정류장.csv"
    bus_path = os.path.join('./data', target_bus_file)
    
    if os.path.exists(bus_path):
        try:
            try: df_bus = pd.read_csv(bus_path, encoding='utf-8')
            except: df_bus = pd.read_csv(bus_path, encoding='cp949')

            if '자치구' in df_bus.columns:
                bus_cnt = df_bus['자치구'].value_counts().reset_index()
                bus_cnt.columns = ['자치구명', '버스정류장_수']
                
                gdf = gdf.drop(columns=['버스정류장_수', '버스정류장 밀도'], errors='ignore')
                gdf = gdf.merge(bus_cnt, on='자치구명', how='left')
                gdf['버스정류장_수'] = gdf['버스정류장_수'].fillna(0)
                gdf['버스정류장 밀도'] = gdf['버스정류장_수'] / gdf['면적(km²)']
                data_info['버스'] = {'file': target_bus_file, 'status': '✅'}
            else:
                data_info['버스'] = {'file': target_bus_file, 'status': '⚠️ 컬럼 오류'}
        except Exception as e:
            data_info['버스'] = {'file': target_bus_file, 'status': '❌', 'desc': str(e)}
    else:
        # 기존 로직 (생략)
        bus_files = [f for f in os.listdir('./data') if 'Station' in f]
        if bus_files:
            bus_path = os.path.join('./data', bus_files[0])
            try:
                if bus_path.lower().endswith('.csv'):
                    try: df_bus = pd.read_csv(bus_path, encoding='cp949')
                    except: df_bus = pd.read_csv(bus_path, encoding='utf-8')
                else: df_bus = pd.read_excel(bus_path, engine='openpyxl')
                x_c = next((c for c in ['X', 'x', '경도'] if c in df_bus.columns), None)
                y_c = next((c for c in ['Y', 'y', '위도'] if c in df_bus.columns), None)
                if x_c and y_c:
                    df_bus = df_bus.dropna(subset=[x_c, y_c])
                    if df_bus[x_c].iloc[0] <= 180:
                        geom = [Point(xy) for xy in zip(df_bus[x_c], df_bus[y_c])]
                        gdf_bus = geopandas.GeoDataFrame(df_bus, geometry=geom, crs="EPSG:4326")
                        joined = geopandas.sjoin(gdf_bus, gdf, how="inner", predicate="within")
                        cnt = joined.groupby('자치구명').size().reset_index(name='버스정류장_수')
                        gdf = gdf.drop(columns=['버스정류장_수', '버스정류장 밀도'], errors='ignore')
                        gdf = gdf.merge(cnt, on='자치구명', how='left')
                        gdf['버스정류장_수'] = gdf['버스정류장_수'].fillna(0)
                        gdf['버스정류장 밀도'] = gdf['버스정류장_수'] / gdf['면적(km²)']
                        data_info['버스'] = {'file': bus_files[0], 'status': '✅ (좌표)'}
            except: pass
        else:
            data_info['버스'] = {'file': '없음', 'status': '❌'}

    # 4. 지하철
    target_subway_file = "서울교통공사_자치구별 지하철역 정보_20250804.CSV"
    sub_path = os.path.join('./data', target_subway_file)
    
    if os.path.exists(sub_path):
        try:
            try: df_sub = pd.read_csv(sub_path, encoding='utf-8')
            except: df_sub = pd.read_csv(sub_path, encoding='cp949')

            if '자치구' in df_sub.columns and '역개수' in df_sub.columns:
                df_sub = df_sub.rename(columns={'자치구': '자치구명', '역개수': '지하철역_수'})
                gdf = gdf.drop(columns=['지하철역_수', '지하철역 밀도'], errors='ignore')
                gdf = gdf.merge(df_sub[['자치구명', '지하철역_수']], on='자치구명', how='left')
                data_info['지하철'] = {'file': target_subway_file, 'status': '✅'}
            else:
                data_info['지하철'] = {'file': target_subway_file, 'status': '⚠️ 컬럼 오류'}
        except:
            data_info['지하철'] = {'file': target_subway_file, 'status': '❌'}
    else:
        # 기존 로직
        sub_files = [f for f in os.listdir('./data') if 'subway' in f.lower() or '지하철' in f]
        if sub_files:
             data_info['지하철'] = {'file': sub_files[0], 'status': '⚠️ (기존 파일)'}
        else:
             data_info['지하철'] = {'file': '없음', 'status': '❌'}
    
    gdf['지하철역_수'] = gdf['지하철역_수'].fillna(0)
    if '지하철역 밀도' not in gdf.columns:
        gdf['지하철역 밀도'] = gdf['지하철역_수'] / gdf['면적(km²)']
    else:
        gdf['지하철역 밀도'] = gdf['지하철역 밀도'].fillna(0)

    # 5. 통계
    gdf['총_교통수단_수'] = gdf.get('버스정류장_수', 0) + gdf.get('지하철역_수', 0)
    gdf['대중교통 밀도 (면적당)'] = gdf['총_교통수단_수'] / gdf['면적(km²)']
    pop_safe = gdf['총_상주인구_수'].replace(0, 1)
    
    # [핵심 수정] 인구 10,000명당 대중교통 수
    gdf['대중교통 수 (인구 만명당)'] = (gdf['총_교통수단_수'] / pop_safe) * 10000
    
    # 부족 순위 (적을수록 1위)
    gdf['교통 부족 순위'] = gdf['대중교통 수 (인구 만명당)'].rank(ascending=True, method='min')

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
        '대중교통 수 (인구 만명당)': '대중교통 수 (인구 만명당)',
        '교통 부족 순위': '교통 부족 순위 (위)'
    }
    gdf = gdf.rename(columns={k: v for k, v in rename_map.items() if k in gdf.columns})
    return gdf, logs, data_info

# --------------------------------------------------------------------------
# 3. 화면 구성 및 시각화
# --------------------------------------------------------------------------
data_result = load_and_merge_data()
if data_result is None or data_result[0] is None:
    st.error("데이터 로드 실패")
    st.stop()

gdf, logs, data_info = data_result

page_mode = st.sidebar.radio("페이지 이동", ["🏙️ 서울시 전체 분석", "📍 자치구별 상세 리포트"])
st.sidebar.markdown("---")

# --------------------------------------------------------------------------
# PAGE 1: 서울시 전체 분석
# --------------------------------------------------------------------------
if page_mode == "🏙️ 서울시 전체 분석":
    st.title("🏙️ 서울시 도시계획 종합 분석")
    
    st.sidebar.header("🔍 분석 옵션")
    metrics_order = [
        '총 상주인구 수 (명)', '인구 밀도 (명/km²)', '집객시설 수 (개)',
        '버스정류장 밀도 (개/km²)', '지하철역 밀도 (개/km²)', '대중교통 밀도 (개/km²)',
        '대중교통 수 (인구 만명당)', '교통 부족 순위 (위)' # 만명당 지표 적용
    ]
    if '버스정류장 수 (개)' in metrics_order:
        metrics_order.insert(0, metrics_order.pop(metrics_order.index('버스정류장 수 (개)')))

    valid_metrics = [m for m in metrics_order if m in gdf.columns]
    
    if valid_metrics:
        selected_col = st.sidebar.radio("분석할 지표", valid_metrics)
        display_count = st.sidebar.slider("그래프 표시 개수", 5, 25, 10)
        
        if '부족' in selected_col: colorscale = 'Reds_r'
        elif '밀도' in selected_col: colorscale = 'YlOrRd'
        elif '인구' in selected_col: colorscale = 'Blues'
        elif '개)' in selected_col: colorscale = 'Greens'
        else: colorscale = 'Viridis'

        st.subheader(f"🗺️ 서울시 {selected_col} 지도")
        
        hover_data_cols = [
            '자치구명', '총 상주인구 수 (명)', '면적 (km²)', 
            '버스정류장 수 (개)', '지하철역 수 (개)', '대중교통 수 (인구 만명당)'
        ]
        final_hover_cols = [c for c in hover_data_cols if c in gdf.columns]

        fig = px.choropleth_mapbox(
            gdf, geojson=gdf.geometry.__geo_interface__, locations=gdf.index,
            color=selected_col, mapbox_style="carto-positron", zoom=9.5,
            center={"lat": 37.5665, "lon": 126.9780}, opacity=0.6,
            hover_name='자치구명', 
            hover_data=final_hover_cols,
            color_continuous_scale=colorscale
        )
        
        num_fmt = ":.2f" if '만명당' in selected_col or '밀도' in selected_col else ":.0f"
        
        fig.update_traces(
            hovertemplate="<b>%{customdata[0]}</b><br>" + 
                          f"{selected_col}: %{{z{num_fmt}}}<br>" + 
                          "<extra></extra>"
        )
        
        fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=500)
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        st.subheader(f"📊 {selected_col} 순위")
        avg_val = gdf[selected_col].mean()
        
        col1, col2 = st.columns([1, 4])
        with col1:
            sort_opt = st.radio("정렬 기준", ["상위", "하위"])
        
        ascending = True if sort_opt == "하위" else False
        if '부족' in selected_col: ascending = not ascending

        df_sorted = gdf.sort_values(by=selected_col, ascending=ascending).head(display_count)
        
        fig_bar = px.bar(
            df_sorted, x='자치구명', y=selected_col, text=selected_col, 
            color=selected_col, color_continuous_scale=colorscale
        )
        
        avg_fmt = ",.0f" if '명)' in selected_col or '개)' in selected_col or '위)' in selected_col else ",.2f"
        fig_bar.add_hline(y=avg_val, line_dash="dash", line_color="white", annotation_text=f"평균: {avg_val:{avg_fmt}}", annotation_font_color="white")
        
        fmt = '%{text:,.0f}' if '명)' in selected_col or '개)' in selected_col or '위)' in selected_col else '%{text:,.2f}'
        fig_bar.update_traces(texttemplate=fmt, textposition='outside')
        fig_bar.update_layout(showlegend=
