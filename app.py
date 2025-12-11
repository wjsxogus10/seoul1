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
        data_info['지도'] = {'file': 'seoul_municipalities_geo_simple.json', 'status': '✅', 'desc': '서울시 행정구역 경계'}
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
        data_info['인구'] = {'file': pop_file, 'status': '✅', 'desc': '자치구별 상주인구 통계'}
    except: 
        data_info['인구'] = {'file': pop_file, 'status': '❌', 'desc': '파일 없음'}

    # 2. 상권
    biz_file = '서울시 상권분석서비스(집객시설-자치구).csv'
    try:
        df_biz = pd.read_csv(f'./data/{biz_file}', encoding='cp949')
        grp = df_biz.groupby('자치구_코드_명')['집객시설_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.drop(columns=['집객시설 수'], errors='ignore')
        gdf = gdf.merge(grp, on='자치구명', how='left')
        gdf['집객시설 수'] = gdf['집객시설_수'].fillna(0)
        data_info['상권'] = {'file': biz_file, 'status': '✅', 'desc': '자치구별 집객시설 수'}
    except:
        data_info['상권'] = {'file': biz_file, 'status': '❌', 'desc': '파일 없음'}

    # 3. 버스
    bus_files = [f for f in os.listdir('./data') if 'Station' in f or '버스' in f]
    if bus_files:
        bus_path = bus_files[0]
        try:
            full_path = os.path.join('./data', bus_path)
            if bus_path.lower().endswith('.csv'):
                try: df_bus = pd.read_csv(full_path, encoding='cp949')
                except: df_bus = pd.read_csv(full_path, encoding='utf-8')
            else:
                df_bus = pd.read_excel(full_path, engine='openpyxl')

            x_c = next((c for c in ['X', 'x', '경도', 'lon'] if c in df_bus.columns), None)
            y_c = next((c for c in ['Y', 'y', '위도', 'lat'] if c in df_bus.columns), None)

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
                    data_info['버스'] = {'file': bus_path, 'status': '✅', 'desc': f'좌표 매칭 완료 ({len(joined)}개)'}
                else:
                    data_info['버스'] = {'file': bus_path, 'status': '⚠️', 'desc': '좌표계 오류 (위경도 아님)'}
            else:
                data_info['버스'] = {'file': bus_path, 'status': '⚠️', 'desc': '좌표 컬럼 없음'}
        except Exception as e:
            data_info['버스'] = {'file': bus_path, 'status': '❌', 'desc': str(e)}
    else:
        data_info['버스'] = {'file': '없음', 'status': '❌', 'desc': '파일 없음'}

    # 4. 지하철
    sub_files = [f for f in os.listdir('./data') if 'subway' in f.lower() or '지하철' in f]
    if sub_files:
        sub_path = sub_files[0]
        try:
            full_path = os.path.join('./data', sub_path)
            if sub_path.lower().endswith('.csv'):
                try: df_sub = pd.read_csv(full_path, encoding='cp949')
                except: df_sub = pd.read_csv(full_path, encoding='utf-8')
            else:
                df_sub = pd.read_excel(full_path, engine='openpyxl')

            if '자치구_코드_명' in df_sub.columns and '지하철역_수' in df_sub.columns:
                df_sub = df_sub.rename(columns={'자치구_코드_명': '자치구명'})
                d_col = next((c for c in df_sub.columns if '밀도' in c), None)
                if d_col: df_sub = df_sub.rename(columns={d_col: '지하철역 밀도'})
                gdf = gdf.drop(columns=['지하철역_수', '지하철역 밀도'], errors='ignore')
                cols = ['자치구명', '지하철역_수']
                if '지하철역 밀도' in df_sub.columns: cols.append('지하철역 밀도')
                gdf = gdf.merge(df_sub[cols], on='자치구명', how='left')
                data_info['지하철'] = {'file': sub_path, 'status': '✅', 'desc': '통계 데이터 병합'}
            else:
                x_c = next((c for c in ['경도', 'X', 'x'] if c in df_sub.columns), None)
                y_c = next((c for c in ['위도', 'Y', 'y'] if c in df_sub.columns), None)
                if x_c and y_c:
                    df_sub = df_sub.dropna(subset=[x_c, y_c])
                    geom = [Point(xy) for xy in zip(df_sub[x_c], df_sub[y_c])]
                    gdf_sub = geopandas.GeoDataFrame(df_sub, geometry=geom, crs="EPSG:4326")
                    joined = geopandas.sjoin(gdf_sub, gdf, how="inner", predicate="within")
                    cnt = joined.groupby('자치구명').size().reset_index(name='지하철역_수')
                    gdf = gdf.drop(columns=['지하철역_수', '지하철역 밀도'], errors='ignore')
                    gdf = gdf.merge(cnt, on='자치구명', how='left')
                    data_info['지하철'] = {'file': sub_path, 'status': '✅', 'desc': f'좌표 매칭 완료 ({len(joined)}개)'}
                else:
                    data_info['지하철'] = {'file': sub_path, 'status': '⚠️', 'desc': '컬럼 오류'}
            
            gdf['지하철역_수'] = gdf['지하철역_수'].fillna(0)
            if '지하철역 밀도' not in gdf.columns:
                gdf['지하철역 밀도'] = gdf['지하철역_수'] / gdf['면적(km²)']
            else:
                gdf['지하철역 밀도'] = gdf['지하철역 밀도'].fillna(0)

        except Exception as e:
            data_info['지하철'] = {'file': sub_path, 'status': '❌', 'desc': str(e)}
    else:
        data_info['지하철'] = {'file': '없음', 'status': '❌', 'desc': '파일 없음'}

    # 5. 통계
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
        '인구 대비 교통수단 비율 (개/명)', '교통 부족 순위 (위)'
    ]
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
        fig = px.choropleth_mapbox(
            gdf, geojson=gdf.geometry.__geo_interface__, locations=gdf.index,
            color=selected_col, mapbox_style="carto-positron", zoom=9.5,
            center={"lat": 37.5665, "lon": 126.9780}, opacity=0.6,
            hover_name='자치구명', color_continuous_scale=colorscale
        )
        is_float = '밀도' in selected_col or '비율' in selected_col
        num_format = ",.4f" if is_float else ",.0f"
        fig.update_traces(hovertemplate=f"<b>%{{hovertext}}</b><br><br>{selected_col}: %{{z:{num_format}}}<extra></extra>")
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
        
        avg_fmt = ",.0f" if '명)' in selected_col or '개)' in selected_col or '위)' in selected_col else ",.4f"
        fig_bar.add_hline(y=avg_val, line_dash="dash", line_color="black", annotation_text=f"평균: {avg_val:{avg_fmt}}", annotation_font_color="black")
        
        fmt = '%{text:,.0f}' if '명)' in selected_col or '개)' in selected_col or '위)' in selected_col else '%{text:,.4f}'
        fig_bar.update_traces(texttemplate=fmt, textposition='outside')
        fig_bar.update_layout(showlegend=False, xaxis_title=None, height=500, margin={"r":0,"t":20,"l":0,"b":0}, coloraxis_showscale=False)
        st.plotly_chart(fig_bar, use_container_width=True)

# --------------------------------------------------------------------------
# PAGE 2: 자치구별 상세 리포트
# --------------------------------------------------------------------------
else:
    st.title("📍 자치구별 상세 리포트")
    
    district_list = sorted(gdf['자치구명'].unique().tolist())
    selected_district = st.sidebar.selectbox("자치구 선택", district_list)
    
    st.markdown(f"### **{selected_district}** 도시계획 현황판")
    st.markdown("---")

    try:
        target_row = gdf[gdf['자치구명'] == selected_district].iloc[0]
        
        c1, c2, c3, c4 = st.columns(4)
        pop_val = target_row.get('총 상주인구 수 (명)', 0)
        area_val = target_row.get('면적 (km²)', 0)
        ratio_val = target_row.get('인구 대비 교통수단 비율 (개/명)', 0)
        rank_val = target_row.get('교통 부족 순위 (위)', 0)
        
        avg_ratio = gdf['인구 대비 교통수단 비율 (개/명)'].mean() if '인구 대비 교통수단 비율 (개/명)' in gdf.columns else 0
        diff = ratio_val - avg_ratio

        with c1: st.metric("👥 총 인구", f"{pop_val:,.0f}명")
        with c2: st.metric("🗺️ 면적", f"{area_val:.2f}km²")
        with c3: st.metric("🚌 교통 비율", f"{ratio_val:.4f}", delta=f"{diff:.4f} (평균 대비)")
        with c4: st.metric("🚨 부족 순위", f"{rank_val:.0f}위", help="1위에 가까울수록 개선이 시급함")
        
        total_trans = target_row.get('총_교통수단_수', 0)
        st.info(f"ℹ️ **{selected_district}**에는 총 **{int(total_trans)}개**의 대중교통 시설(버스+지하철)이 있습니다.")
        
        st.markdown("---")

        col_d1, col_d2 = st.columns([1, 1])
        
        with col_d1:
            st.subheader(f"🗺️ {selected_district} 위치")
            district_geo = gdf[gdf['자치구명'] == selected_district]
            center_lat = district_geo.geometry.centroid.y.values[0]
            center_lon = district_geo.geometry.centroid.x.values[0]
            
            fig_d = px.choropleth_mapbox(
                gdf, geojson=gdf.geometry.__geo_interface__, locations=gdf.index,
                color='교통 부족 순위 (위)', mapbox_style="carto-positron", zoom=11,
                center={"lat": center_lat, "lon": center_lon}, opacity=0.1,
                hover_name='자치구명', color_continuous_scale='Reds_r'
            )
            fig_d.add_trace(
                px.choropleth_mapbox(
                    district_geo, geojson=district_geo.geometry.__geo_interface__, locations=district_geo.index,
                    color_discrete_sequence=['#FF4B4B'], opacity=0.9
                ).data[0]
            )
            fig_d.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=400, showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig_d, use_container_width=True)

        with col_d2:
            st.subheader("📊 교통 부족 순위 비교 (낮을수록 시급)")
            
            my_val = rank_val
            avg_rank = gdf['교통 부족 순위 (위)'].mean()
            
            df_comp = pd.DataFrame({
                '구분': [selected_district, '서울시 평균'],
                '순위': [my_val, avg_rank],
                '색상': ['My', 'Avg']
            })
            
            fig_comp = px.bar(
                df_comp, x='구분', y='순위', color='색상',
                color_discrete_map={'My': '#FF4B4B', 'Avg': 'lightgray'},
                text='순위'
            )
            fig_comp.update_traces(texttemplate='%{text:.0f}위', textposition='outside')
            fig_comp.update_layout(showlegend=False, margin={"r":0,"t":40,"l":0,"b":0}, height=400, yaxis_title="순위 (숫자가 작을수록 부족함)")
            st.plotly_chart(fig_comp, use_container_width=True)

    except Exception as e:
        st.error(f"상세 정보를 표시하는 중 오류가 발생했습니다: {e}")

# --------------------------------------------------------------------------
# [하단] 데이터 출처 표시 (Footer)
# --------------------------------------------------------------------------
st.markdown("---")
with st.expander("📚 사용된 데이터 출처 보기", expanded=False):
    st.markdown("#### 📂 데이터 파일 현황")
    
    # 데이터 정보를 표(DataFrame)로 변환하여 깔끔하게 표시
    source_list = []
    for cat, info in data_info.items():
        source_list.append({
            "데이터 종류": cat,
            "상태": info['status'],
            "파일명": info['file'],
            "비고": info['desc']
        })
    
    df_source = pd.DataFrame(source_list)
    st.dataframe(df_source, use_container_width=True, hide_index=True)
