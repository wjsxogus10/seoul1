import streamlit as st
import pandas as pd
import geopandas
import plotly.express as px
import os

# --------------------------------------------------------------------------
# 1. 기본 설정 (가장 먼저 실행)
# --------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="서울시 도시계획 대시보드")

# --------------------------------------------------------------------------
# 2. 헬퍼 함수: 데이터 정제 (숫자 변환기)
# --------------------------------------------------------------------------
def to_float(value):
    """ '1,234' 같은 문자열이나 공백을 안전하게 숫자로 변환 """
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        value = value.replace(',', '').strip()
        if value == '': return 0
        try:
            return float(value)
        except:
            return 0
    return 0

# --------------------------------------------------------------------------
# 3. 데이터 로드 및 병합 (핵심 로직)
# --------------------------------------------------------------------------
@st.cache_data(ttl=600)
def get_dataset():
    status = {} # 데이터 로드 상태 기록
    
    # [1] 지도 데이터 (GeoJSON)
    # 서울시 자치구 경계 데이터 (웹에서 로드)
    geojson_url = "https://raw.githubusercontent.com/southkorea/seoul-maps/master/kostat/2013/json/seoul_municipalities_geo_simple.json"
    try:
        gdf = geopandas.read_file(geojson_url)
        gdf = gdf.to_crs(epsg=4326) # 좌표계 통일
        
        # 컬럼명 통일 (영어/한글 모두 '자치구명'으로 변경)
        if 'name' in gdf.columns: gdf = gdf.rename(columns={'name': '자치구명'})
        elif 'SIG_KOR_NM' in gdf.columns: gdf = gdf.rename(columns={'SIG_KOR_NM': '자치구명'})
        
        # 면적 계산 (WGS84 -> TM좌표 변환 후 계산)
        gdf_area = gdf.to_crs(epsg=5179)
        gdf['면적(km²)'] = gdf_area.geometry.area / 1_000_000
        status['지도'] = '✅ 성공'
    except Exception as e:
        st.error(f"지도 데이터를 불러올 수 없습니다: {e}")
        return None, status

    # [2] 초기화 (데이터가 없을 때를 대비해 0으로 채움)
    for col in ['총 상주인구 수', '버스정류장 수', '지하철역 수']:
        gdf[col] = 0

    # 파일 찾기 함수 (현재폴더 또는 data 폴더 검색)
    def find_path(filename):
        if os.path.exists(filename): return filename
        if os.path.exists(f'./data/{filename}'): return f'./data/{filename}'
        return None

    # -----------------------------------------------------------
    # [A] 인구 데이터 병합
    # -----------------------------------------------------------
    pop_file = find_path('서울시 상권분석서비스(상주인구-자치구).csv')
    if pop_file:
        try:
            df = pd.read_csv(pop_file, encoding='cp949')
            # 숫자 변환 적용
            df['총_상주인구_수'] = df['총_상주인구_수'].apply(to_float)
            
            # 자치구별 평균 구하기
            grp = df.groupby('자치구_코드_명')['총_상주인구_수'].mean().reset_index()
            grp.columns = ['자치구명', '총 상주인구 수']
            
            # 지도 데이터에 병합
            gdf = gdf.drop(columns=['총 상주인구 수'], errors='ignore')
            gdf = gdf.merge(grp, on='자치구명', how='left')
            status['인구'] = '✅ 성공'
        except: status['인구'] = '❌ 읽기 실패'
    else: status['인구'] = '⚠️ 파일 없음'

    # -----------------------------------------------------------
    # [B] 버스 데이터 병합
    # -----------------------------------------------------------
    bus_file = find_path('20250930기준_서울시정류소(정류소별).xlsx - 시내버스 정류장.csv')
    if bus_file:
        try:
            # 인코딩 자동 감지 시도
            try: df = pd.read_csv(bus_file, encoding='utf-8')
            except: df = pd.read_csv(bus_file, encoding='cp949')
            
            if '자치구' in df.columns:
                cnt = df['자치구'].value_counts().reset_index()
                cnt.columns = ['자치구명', '버스정류장 수']
                
                gdf = gdf.drop(columns=['버스정류장 수'], errors='ignore')
                gdf = gdf.merge(cnt, on='자치구명', how='left')
                status['버스'] = '✅ 성공'
            else: status['버스'] = '⚠️ 컬럼 오류'
        except: status['버스'] = '❌ 읽기 실패'
    else: status['버스'] = '⚠️ 파일 없음'

    # -----------------------------------------------------------
    # [C] 지하철 데이터 병합
    # -----------------------------------------------------------
    sub_file = find_path('서울교통공사_자치구별 지하철역 정보_20250804.CSV')
    if sub_file:
        try:
            try: df = pd.read_csv(sub_file, encoding='utf-8')
            except: df = pd.read_csv(sub_file, encoding='cp949')
            
            if '자치구' in df.columns and '역개수' in df.columns:
                df = df.rename(columns={'자치구': '자치구명', '역개수': '지하철역 수'})
                df['지하철역 수'] = df['지하철역 수'].apply(to_float)
                
                gdf = gdf.drop(columns=['지하철역 수'], errors='ignore')
                gdf = gdf.merge(df[['자치구명', '지하철역 수']], on='자치구명', how='left')
                status['지하철'] = '✅ 성공'
            else: status['지하철'] = '⚠️ 컬럼 오류'
        except: status['지하철'] = '❌ 읽기 실패'
    else: status['지하철'] = '⚠️ 파일 없음'

    # -----------------------------------------------------------
    # [D] 최종 지표 계산 (NaN 처리 필수)
    # -----------------------------------------------------------
    gdf = gdf.fillna(0)
    
    # 1. 인구 밀도
    gdf['인구 밀도'] = gdf['총 상주인구 수'] / gdf['면적(km²)'].replace(0, 1)
    
    # 2. 총 대중교통 수
    gdf['총 대중교통 수'] = gdf['버스정류장 수'] + gdf['지하철역 수']
    
    # 3. 인구 1,000명당 대중교통 수 (핵심 지표)
    pop_safe = gdf['총 상주인구 수'].replace(0, 1) # 0 나누기 방지
    gdf['천명당 대중교통'] = (gdf['총 대중교통 수'] / pop_safe) * 1000
    
    # 4. 부족 순위 (적을수록 1위)
    gdf['부족 순위'] = gdf['천명당 대중교통'].rank(ascending=True, method='min')

    return gdf, status

# --------------------------------------------------------------------------
# 4. 화면 UI 구성
# --------------------------------------------------------------------------
# 데이터 로드
gdf, load_status = get_dataset()

# 데이터 로드 실패 시 중단
if gdf is None:
    st.stop()

# 사이드바 설정
with st.sidebar:
    st.header("📊 메뉴 선택")
    page = st.radio("이동할 페이지", ["🏙️ 서울시 전체 분석", "🧩 유형별 4분면 분석", "📍 자치구별 상세 리포트"])
    
    st.markdown("---")
    with st.expander("📂 데이터 로드 상태 확인"):
        st.write(load_status)
        st.caption("※ '⚠️ 파일 없음'이 뜨면 data 폴더에 파일을 넣어주세요.")

# ==========================================================================
# PAGE 1: 서울시 전체 분석
# ==========================================================================
if page == "🏙️ 서울시 전체 분석":
    st.title("🏙️ 서울시 도시계획 종합 분석")
    st.markdown("서울시 25개 자치구의 **인구, 면적, 대중교통 현황**을 종합적으로 분석합니다.")

    # 옵션 선택
    metrics = {
        '천명당 대중교통 (개)': '천명당 대중교통',
        '교통 부족 순위 (위)': '부족 순위',
        '인구 밀도 (명/km²)': '인구 밀도',
        '총 상주인구 (명)': '총 상주인구 수',
        '버스정류장 수 (개)': '버스정류장 수'
    }
    selected_label = st.selectbox("지도에 표시할 데이터", list(metrics.keys()))
    selected_col = metrics[selected_label]

    # 색상 결정 (부족 순위는 빨간색, 나머지는 파란/초록색)
    if '순위' in selected_col: color_scale = 'Reds_r' # 1위가 진하게
    elif '천명당' in selected_col: color_scale = 'YlGnBu'
    else: color_scale = 'Viridis'

    # [1] 지도 시각화
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader(f"🗺️ {selected_label} 지도")
        fig_map = px.choropleth_mapbox(
            gdf, 
            geojson=gdf.geometry.__geo_interface__, 
            locations=gdf.index,
            color=selected_col, 
            color_continuous_scale=color_scale,
            mapbox_style="carto-positron", 
            zoom=9.8, 
            center={"lat": 37.5665, "lon": 126.9780},
            opacity=0.6,
            hover_name='자치구명',
            hover_data=['총 상주인구 수', '버스정류장 수', '천명당 대중교통']
        )
        fig_map.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, height=500)
        st.plotly_chart(fig_map, use_container_width=True)

    # [2] 순위 그래프
    with col2:
        st.subheader("📊 자치구별 순위")
        # 정렬 (순위는 오름차순, 나머지는 내림차순)
        asc = True if '순위' in selected_col else False
        df_sorted = gdf.sort_values(by=selected_col, ascending=asc)
        
        fig_bar = px.bar(
            df_sorted, 
            x=selected_col, 
            y='자치구명', 
            orientation='h',
            text=selected_col,
            color=selected_col, 
            color_continuous_scale=color_scale
        )
        fig_bar.update_layout(yaxis={'categoryorder':'total ascending'}, showlegend=False, height=500, margin={"l":0,"r":0,"t":0,"b":0})
        fig_bar.update_traces(texttemplate='%{text:,.1f}', textposition='outside')
        st.plotly_chart(fig_bar, use_container_width=True)

# ==========================================================================
# PAGE 2: 유형별 4분면 분석 (산점도)
# ==========================================================================
elif page == "🧩 유형별 4분면 분석":
    st.title("🧩 도시 유형별 4분면 분석")
    st.info("💡 **X축: 인구밀도(수요)** vs **Y축: 천명당 교통수(공급)** 관계를 분석합니다.")

    # 데이터 검증 (인구가 0이면 차트가 안 그려짐)
    if gdf['총 상주인구 수'].sum() == 0:
        st.error("🚨 인구 데이터가 로드되지 않아 분석할 수 없습니다. 파일을 확인해주세요.")
    else:
        # 차트 그리기
        fig_scatter = px.scatter(
            gdf,
            x='인구 밀도',
            y='천명당 대중교통',
            text='자치구명',
            size='총 상주인구 수', # 인구가 많으면 점이 커짐
            color='부족 순위',
            color_continuous_scale='Reds_r',
            hover_name='자치구명',
            size_max=40
        )

        # 평균선 추가 (4분면 기준)
        avg_x = gdf['인구 밀도'].mean()
        avg_y = gdf['천명당 대중교통'].mean()

        fig_scatter.add_vline(x=avg_x, line_dash="dash", line_color="gray", annotation_text="평균 밀도")
        fig_scatter.add_hline(y=avg_y, line_dash="dash", line_color="gray", annotation_text="평균 공급")
        
        fig_scatter.update_traces(textposition='top center')
        fig_scatter.update_layout(height=600, showlegend=False)
        st.plotly_chart(fig_scatter, use_container_width=True)
        
        st.success("""
        **🔎 그래프 해석 가이드**
        - **오른쪽 아래 (↘️):** 인구 밀도는 높은데(사람 많음), 교통 시설은 적은 곳입니다. **(개선 시급 지역)**
        - **왼쪽 위 (↖️):** 인구 밀도는 낮은데, 교통 시설은 풍부한 곳입니다. **(교통 여유 지역)**
        """)

# ==========================================================================
# PAGE 3: 자치구별 상세 리포트
# ==========================================================================
elif page == "📍 자치구별 상세 리포트":
    st.title("📍 자치구별 상세 리포트")
    
    # 자치구 선택
    gu_list = sorted(gdf['자치구명'].unique())
    selected_gu = st.selectbox("분석할 자치구를 선택하세요", gu_list)
    
    # 선택한 자치구 데이터 가져오기
    row = gdf[gdf['자치구명'] == selected_gu].iloc[0]
    
    # [1] 핵심 지표 카드
    col1, col2, col3, col4 = st.columns(4)
    avg_score = gdf['천명당 대중교통'].mean()
    diff = row['천명당 대중교통'] - avg_score
    
    with col1: st.metric("👥 인구", f"{int(row['총 상주인구 수']):,}명")
    with col2: st.metric("🚌 총 교통시설", f"{int(row['총 대중교통 수']):,}개")
    with col3: st.metric("📊 천명당 교통", f"{row['천명당 대중교통']:.2f}개", delta=f"{diff:.2f} (평균대비)")
    with col4: st.metric("🚨 부족 순위", f"{int(row['부족 순위'])}위", help="1위에 가까울수록 부족함")

    st.divider()

    # [2] 상세 위치 지도
    col_map, col_chart = st.columns([1, 1])
    
    with col_map:
        st.subheader(f"🗺️ {selected_gu} 위치")
        # 선택된 구만 빨간색으로 표시
        gdf['color_group'] = gdf['자치구명'].apply(lambda x: '선택됨' if x == selected_gu else '기타')
        
        fig_gu = px.choropleth_mapbox(
            gdf, geojson=gdf.geometry.__geo_interface__, locations=gdf.index,
            color='color_group',
            color_discrete_map={'선택됨': 'red', '기타': 'lightgray'},
            mapbox_style="carto-positron", zoom=10,
            center={"lat": 37.5665, "lon": 126.9780}, opacity=0.6,
            hover_name='자치구명'
        )
        fig_gu.update_layout(showlegend=False, margin={"r":0,"t":0,"l":0,"b":0}, height=400)
        st.plotly_chart(fig_gu, use_container_width=True)

    # [3] 비교 그래프
    with col_chart:
        st.subheader("📊 서울시 평균과 비교")
        
        comp_data = pd.DataFrame({
            '구분': [selected_gu, '서울시 평균'],
            '천명당 교통수': [row['천명당 대중교통'], avg_score]
        })
        
        fig_comp = px.bar(
            comp_data, x='구분', y='천명당 교통수', 
            color='구분', color_discrete_sequence=['red', 'gray'],
            text='천명당 교통수'
        )
        fig_comp.update_traces(texttemplate='%{text:.2f}개', textposition='outside')
        fig_comp.update_layout(showlegend=False, height=400)
        st.plotly_chart(fig_comp, use_container_width=True)
