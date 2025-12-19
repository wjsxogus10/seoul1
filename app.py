import streamlit as st
import pandas as pd
import geopandas
import plotly.express as px
import plotly.graph_objects as go
import os
from shapely.geometry import Point
import numpy as np

# --------------------------------------------------------------------------
# 1. 페이지 설정
# --------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="서울시 대중교통 개선 대시보드")

# --------------------------------------------------------------------------
# 2. 데이터 로드 및 병합 함수
# --------------------------------------------------------------------------
@st.cache_data(ttl=600)
def load_and_merge_data():
    logs = []
    data_info = {} # 데이터 정보 저장

    # [헬퍼 함수] 숫자 변환
    def clean_numeric(value):
        if isinstance(value, str):
            try: return float(value.replace(',', '').strip())
            except: return 0
        return value

    # [A] 지도 데이터
    map_url = "https://raw.githubusercontent.com/southkorea/seoul-maps/master/kostat/2013/json/seoul_municipalities_geo_simple.json"
    try:
        gdf = geopandas.read_file(map_url)
        gdf = gdf.to_crs(epsg=4326)
        if 'name' in gdf.columns: gdf = gdf.rename(columns={'name': '자치구명'})
        elif 'SIG_KOR_NM' in gdf.columns: gdf = gdf.rename(columns={'SIG_KOR_NM': '자치구명'})
        
        # 불필요한 base_year 제거
        if 'base_year' in gdf.columns: gdf = gdf.drop(columns=['base_year'])
            
        gdf_area = gdf.to_crs(epsg=5179)
        gdf['면적(km²)'] = gdf_area.geometry.area / 1_000_000
        data_info['지도'] = {'file': '서울시 지도', 'status': '✅'}
    except Exception as e:
        return None, [f"❌ 지도 로드 실패: {e}"], {}

    # [B] 초기화
    cols_init = ['총_상주인구_수', '인구 밀도', '버스정류장_수', '버스정류장 밀도', '지하철역_수', '지하철역 밀도', '총_교통수단_수']
    for c in cols_init: gdf[c] = 0

    # 1. 인구
    pop_file = '서울시 상권분석서비스(상주인구-자치구).csv'
    pop_path = None
    if os.path.exists(pop_file): pop_path = pop_file
    elif os.path.exists(f'./data/{pop_file}'): pop_path = f'./data/{pop_file}'

    if pop_path:
        try:
            df_pop = pd.read_csv(pop_path, encoding='cp949')
            df_pop.columns = df_pop.columns.str.strip()
            if '총_상주인구_수' in df_pop.columns:
                df_pop['총_상주인구_수'] = df_pop['총_상주인구_수'].apply(clean_numeric)
            
            grp = df_pop.groupby('자치구_코드_명')['총_상주인구_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
            gdf = gdf.drop(columns=['총_상주인구_수', '인구 밀도'], errors='ignore')
            gdf = gdf.merge(grp, on='자치구명', how='left')
            gdf['총_상주인구_수'] = gdf['총_상주인구_수'].fillna(0)
            gdf['인구 밀도'] = gdf['총_상주인구_수'] / gdf['면적(km²)']
            data_info['인구'] = {'file': pop_file, 'status': '✅'}
        except: 
            data_info['인구'] = {'file': pop_file, 'status': '❌'}
    else:
        data_info['인구'] = {'file': pop_file, 'status': '❌'}

    # 2. 버스
    target_bus_file = "20250930기준_서울시정류소(정류소별).xlsx - 시내버스 정류장.csv"
    bus_path = None
    if os.path.exists(target_bus_file): bus_path = target_bus_file
    elif os.path.exists(f'./data/{target_bus_file}'): bus_path = f'./data/{target_bus_file}'
    
    if bus_path:
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
            data_info['버스'] = {'file': target_bus_file, 'status': '❌'}
    else:
        bus_files = [f for f in os.listdir('./data') if 'Station' in f] if os.path.exists('./data') else []
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
                        data_info['버스'] = {'file': bus_files[0], 'status': '✅'}
            except: pass
        else:
            data_info['버스'] = {'file': '없음', 'status': '❌'}

    # 3. 지하철
    target_subway_file = "서울교통공사_자치구별 지하철역 정보_20250804.CSV"
    sub_path = None
    if os.path.exists(target_subway_file): sub_path = target_subway_file
    elif os.path.exists(f'./data/{target_subway_file}'): sub_path = f'./data/{target_subway_file}'
    
    if sub_path:
        try:
            try: df_sub = pd.read_csv(sub_path, encoding='utf-8')
            except: df_sub = pd.read_csv(sub_path, encoding='cp949')

            if '자치구' in df_sub.columns and '역개수' in df_sub.columns:
                df_sub = df_sub.rename(columns={'자치구': '자치구명', '역개수': '지하철역_수'})
                df_sub['지하철역_수'] = df_sub['지하철역_수'].apply(clean_numeric)
                
                gdf = gdf.drop(columns=['지하철역_수', '지하철역 밀도'], errors='ignore')
                gdf = gdf.merge(df_sub[['자치구명', '지하철역_수']], on='자치구명', how='left')
                data_info['지하철'] = {'file': target_subway_file, 'status': '✅'}
            else:
                data_info['지하철'] = {'file': target_subway_file, 'status': '⚠️'}
        except:
            data_info['지하철'] = {'file': target_subway_file, 'status': '❌'}
    else:
        sub_files = [f for f in os.listdir('./data') if 'subway' in f.lower() or '지하철' in f] if os.path.exists('./data') else []
        if sub_files:
             data_info['지하철'] = {'file': sub_files[0], 'status': '⚠️'}
        else:
             data_info['지하철'] = {'file': '없음', 'status': '❌'}
    
    gdf['지하철역_수'] = gdf['지하철역_수'].fillna(0)
    if '지하철역 밀도' not in gdf.columns:
        gdf['지하철역 밀도'] = gdf['지하철역_수'] / gdf['면적(km²)']
    else:
        gdf['지하철역 밀도'] = gdf['지하철역 밀도'].fillna(0)

    # 4. 통계
    gdf['총_교통수단_수'] = gdf.get('버스정류장_수', 0) + gdf.get('지하철역_수', 0)
    gdf['대중교통 밀도 (면적당)'] = gdf['총_교통수단_수'] / gdf['면적(km²)']
    pop_safe = gdf['총_상주인구_수'].replace(0, 1)
    
    gdf['대중교통 수 (인구 천명당)'] = (gdf['총_교통수단_수'] / pop_safe) * 1000
    gdf['교통 부족 순위'] = gdf['대중교통 수 (인구 천명당)'].rank(ascending=True, method='min')

    rename_map = {
        '총_상주인구_수': '총 상주인구 수 (명)',
        '버스정류장_수': '버스정류장 수 (개)',
        '지하철역_수': '지하철역 수 (개)',
        '면적(km²)': '면적 (km²)',
        '인구 밀도': '인구 밀도 (명/km²)',
        '버스정류장 밀도': '버스정류장 밀도 (개/km²)',
        '지하철역 밀도': '지하철역 밀도 (개/km²)',
        '대중교통 밀도 (면적당)': '대중교통 밀도 (개/km²)',
        '대중교통 수 (인구 천명당)': '대중교통 수 (인구 천명당)',
        '교통 부족 순위': '교통 부족 순위 (위)'
    }
    gdf = gdf.rename(columns={k: v for k, v in rename_map.items() if k in gdf.columns})
    
    # [정리] 컬럼명 밑줄 제거 & 불필요 컬럼 삭제 & 정렬
    gdf.columns = gdf.columns.str.replace('_', ' ')
    gdf = gdf.drop(columns=['base year', 'base_year', '집객시설 수', '집객시설 수 (개)'], errors='ignore')
    if '교통 부족 순위 (위)' in gdf.columns:
        gdf = gdf.sort_values(by='교통 부족 순위 (위)', ascending=True)
    
    return gdf, logs, data_info

# --------------------------------------------------------------------------
# 3. 화면 구성 및 시각화
# --------------------------------------------------------------------------
data_result = load_and_merge_data()
if data_result is None or data_result[0] is None:
    st.error("데이터 로드 실패")
    st.stop()

gdf, logs, data_info = data_result

page_mode = st.sidebar.radio(
    "페이지 이동", 
    ["🏙️ 서울시 대중교통 현황", "🧩 유형별 4분면 분석", "📍 자치구별 상세 리포트"]
)
st.sidebar.markdown("---")

# --------------------------------------------------------------------------
# PAGE 1: 서울시 전체 분석
# --------------------------------------------------------------------------
if page_mode == "🏙️ 서울시 대중교통 현황":
    st.title("🏙️ 서울시 대중교통 현황")
    
    st.sidebar.header("🔍 분석 옵션")
    
    # [자유로운 선택] 가능한 모든 수치형 컬럼 표시
    available_cols = [
        '교통 부족 순위 (위)', '면적 (km²)', '총 상주인구 수 (명)', '인구 밀도 (명/km²)',
        '총 교통수단 수', '대중교통 수 (인구 천명당)',
        '버스정류장 수 (개)', '버스정류장 밀도 (개/km²)', 
        '지하철역 수 (개)', '지하철역 밀도 (개/km²)', '대중교통 밀도 (개/km²)'
    ]
    # 실제 데이터에 있는 컬럼만 필터링
    valid_metrics = [c for c in available_cols if c in gdf.columns]
    
    if valid_metrics:
        selected_col = st.sidebar.selectbox("보고 싶은 순위를 선택하세요", valid_metrics)
        display_count = st.sidebar.slider("그래프 표시 개수", 5, 25, 25)
        
        # 색상 설정
        if '부족' in selected_col: colorscale = 'Reds_r' # 부족할수록 진하게
        elif '면적' in selected_col or '교통' in selected_col: colorscale = 'Greens'
        else: colorscale = 'Blues'

        st.subheader(f"🗺️ 서울시 {selected_col} 지도")
        
        # 지도 그리기
        hover_cols = ['자치구명', '총 상주인구 수 (명)', '면적 (km²)', '총 교통수단 수']
        hover_cols = [c for c in hover_cols if c in gdf.columns]

        fig = px.choropleth_mapbox(
            gdf, geojson=gdf.geometry.__geo_interface__, locations=gdf.index,
            color=selected_col, mapbox_style="carto-positron", zoom=9.5,
            center={"lat": 37.5665, "lon": 126.9780}, opacity=0.6,
            hover_name='자치구명', hover_data=hover_cols,
            color_continuous_scale=colorscale
        )
        fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=500)
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        st.subheader(f"📊 {selected_col} 순위 그래프")
        
        # 정렬 로직 (부족 순위는 오름차순, 나머지는 내림차순이 보통 '상위')
        # 사용자가 자유롭게 보려면 정렬 기준도 주면 좋음
        sort_order = st.radio("정렬 방식", ["높은 순 (Top)", "낮은 순 (Bottom)"], horizontal=True)
        ascending = True if sort_order == "낮은 순 (Bottom)" else False
        
        # 데이터 정렬
        df_sorted = gdf.sort_values(by=selected_col, ascending=ascending).head(display_count)
        
        avg_val = gdf[selected_col].mean()
        
        fig_bar = px.bar(
            df_sorted, x='자치구명', y=selected_col, text=selected_col, 
            color=selected_col, color_continuous_scale=colorscale
        )
        
        # 포맷팅
        if '명)' in selected_col or '개)' in selected_col or '위)' in selected_col or '수' in selected_col:
            fmt = ',.0f'
        else:
            fmt = ',.2f'
            
        fig_bar.update_traces(texttemplate=f'%{{text:{fmt}}}', textposition='outside')
        fig_bar.add_hline(y=avg_val, line_dash="dash", line_color="green", annotation_text=f"평균: {avg_val:{fmt}}")
        fig_bar.update_layout(showlegend=False, margin={"r":0,"t":20,"l":0,"b":0}, height=500, xaxis_title=None)
        st.plotly_chart(fig_bar, use_container_width=True)
        
        # [추가] 상세 데이터 표 보여주기
        st.markdown("---")
        st.subheader(f"📋 {selected_col} 상세 데이터 표")
        
        # 보여줄 컬럼 선택 (geometry 제외)
        display_cols = ['자치구명', selected_col] + [c for c in valid_metrics if c != selected_col]
        st.dataframe(
            df_sorted[display_cols].reset_index(drop=True),
            use_container_width=True
        )

# --------------------------------------------------------------------------
# PAGE 2: 유형별 4분면 분석
# --------------------------------------------------------------------------
elif page_mode == "🧩 유형별 4분면 분석":
    st.title("🧩 도시 유형별 4분면 분석")
    st.markdown("---")
    
    st.subheader("수요(인구밀도) vs 공급(대중교통) 상관관계")
    
    has_pop = gdf['총 상주인구 수 (명)'].sum() > 0
    scat_size = '총 상주인구 수 (명)' if has_pop else None

    scat_fig = px.scatter(
        gdf, 
        x='인구 밀도 (명/km²)', 
        y='대중교통 수 (인구 천명당)', 
        text='자치구명',
        color='교통 부족 순위 (위)', 
        color_continuous_scale='Reds_r',
        hover_data=['총 상주인구 수 (명)', '총 교통수단 수'], 
        size=scat_size,
        size_max=40
    )
    
    if not has_pop:
        scat_fig.update_traces(marker=dict(size=15))

    mean_x = gdf['인구 밀도 (명/km²)'].mean()
    mean_y = gdf['대중교통 수 (인구 천명당)'].mean()

    scat_fig.add_vline(x=mean_x, line_width=1, line_dash="dash", line_color="grey", annotation_text="평균 인구밀도")
    scat_fig.add_hline(y=mean_y, line_width=1, line_dash="dash", line_color="grey", annotation_text="평균 공급수준")

    scat_fig.update_traces(textposition='top center')
    scat_fig.update_layout(height=700, showlegend=False)
    
    st.plotly_chart(scat_fig, use_container_width=True)
    
    st.markdown("---")
    st.subheader("💾 분석 데이터 다운로드")
    df_download = gdf.drop(columns=['geometry'])
    csv = df_download.to_csv(index=False).encode('utf-8-sig')
    
    st.download_button(
        label="📥 최종 분석 데이터(CSV) 받기",
        data=csv,
        file_name='서울시_대중교통_분석결과_최종.csv',
        mime='text/csv',
    )

# --------------------------------------------------------------------------
# PAGE 3: 자치구별 상세 리포트
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
        ratio_val = target_row.get('대중교통 수 (인구 천명당)', 0)
        rank_val = target_row.get('교통 부족 순위 (위)', 0)
        
        avg_ratio = gdf['대중교통 수 (인구 천명당)'].mean() if '대중교통 수 (인구 천명당)' in gdf.columns else 0
        diff = ratio_val - avg_ratio

        with c1: st.metric("👥 총 인구", f"{pop_val:,.0f}명")
        with c2: st.metric("🗺️ 면적", f"{area_val:.2f}km²")
        with c3: st.metric("🚌 천명당 교통수", f"{ratio_val:.2f}개", delta=f"{diff:.2f} (평균 대비)")
        with c4: st.metric("🚨 부족 순위", f"{rank_val:.0f}위", help="1위에 가까울수록 개선이 시급함")
        
        total_trans = target_row.get('총 교통수단 수', 0)
        st.info(f"ℹ️ **{selected_district}**에는 총 **{int(total_trans)}개**의 대중교통 시설(버스+지하철)이 있습니다.")
        
        st.markdown("---")

        col_d1, col_d2 = st.columns([1, 1])
        
        with col_d1:
            st.subheader(f"🗺️ {selected_district} 상세 지도")
            
            district_geo = gdf[gdf['자치구명'] == selected_district]
            center_lat = district_geo.geometry.centroid.y.values[0]
            center_lon = district_geo.geometry.centroid.x.values[0]
            
            hover_cols = [
                '자치구명', '총 상주인구 수 (명)', '면적 (km²)', 
                '버스정류장 수 (개)', '지하철역 수 (개)', 
                '대중교통 수 (인구 천명당)', '교통 부족 순위 (위)'
            ]
            valid_hover = [c for c in hover_cols if c in gdf.columns]

            fig_d = px.choropleth_mapbox(
                gdf, geojson=gdf.geometry.__geo_interface__, locations=gdf.index,
                color='교통 부족 순위 (위)', mapbox_style="carto-positron", zoom=11,
                center={"lat": center_lat, "lon": center_lon}, opacity=0.1,
                hover_name='자치구명', 
                hover_data=valid_hover,
                color_continuous_scale='Reds_r'
            )
            
            fig_d.update_traces(
                hovertemplate="<b>%{customdata[0]}</b><br><br>" +
                "👥 인구: %{customdata[1]:,.0f}명<br>" +
                "🗺️ 면적: %{customdata[2]:.2f}km²<br>" +
                "🚌 버스: %{customdata[3]:,.0f}개<br>" +
                "🚇 지하철: %{customdata[4]:,.0f}개<br>" +
                "📊 천명당: %{customdata[5]:.2f}개<br>" +
                "🚨 순위: %{customdata[6]:.0f}위<extra></extra>"
            )

            highlight_trace = px.choropleth_mapbox(
                district_geo, geojson=district_geo.geometry.__geo_interface__, locations=district_geo.index,
                color_discrete_sequence=['#FF4B4B'], opacity=0.9,
                hover_name='자치구명', hover_data=valid_hover
            ).data[0]
            
            highlight_trace.hovertemplate = fig_d.data[0].hovertemplate
            fig_d.add_trace(highlight_trace)

            fig_d.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=400, showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig_d, use_container_width=True)

        with col_d2:
            st.subheader("📊 교통 부족 순위 비교")
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
            fig_comp.update_layout(showlegend=False, margin={"r":0,"t":40,"l":0,"b":0}, height=400, yaxis_title="순위")
            st.plotly_chart(fig_comp, use_container_width=True)

    except Exception as e:
        st.error(f"상세 정보를 표시하는 중 오류가 발생했습니다: {e}")

# --------------------------------------------------------------------------
# [하단] 데이터 출처 표시 (Footer)
# --------------------------------------------------------------------------
st.markdown("---")
with st.expander("📚 사용된 데이터 출처 보기", expanded=False):
    st.markdown("#### 📂 데이터 파일 현황")
    
    source_list = []
    for cat, info in data_info.items():
        source_list.append({
            "데이터 종류": cat,
            "상태": info.get('status', '❓'),
            "파일명": info.get('file', '-')
        })
    
    df_source = pd.DataFrame(source_list)
    st.dataframe(df_source, use_container_width=True, hide_index=True)
