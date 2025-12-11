@st.cache_data
def load_and_merge_data():
    # -----------------------------------------------------------
    # (A) 지도 데이터 (인터넷 공공 데이터)
    # -----------------------------------------------------------
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

    # -----------------------------------------------------------
    # (B) 사용자 데이터 병합
    # -----------------------------------------------------------
    
    # 1. 인구 데이터
    try:
        df_pop = pd.read_csv('./data/서울시 상권분석서비스(상주인구-자치구).csv', encoding='cp949')
        grp = df_pop.groupby('자치구_코드_명')['총_상주인구_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.merge(grp, on='자치구명', how='left')
        gdf['총_상주인구_수'] = gdf['총_상주인구_수'].fillna(0)
        gdf['인구 밀도'] = gdf['총_상주인구_수'] / gdf['면적(km²)']
    except Exception as e:
        # 인구 데이터 에러는 무시 (질문하신 건 교통이니까)
        pass

    # 2. 상권 데이터
    try:
        df_biz = pd.read_csv('./data/서울시 상권분석서비스(집객시설-자치구).csv', encoding='cp949')
        grp = df_biz.groupby('자치구_코드_명')['집객시설_수'].mean().reset_index().rename(columns={'자치구_코드_명':'자치구명'})
        gdf = gdf.merge(grp, on='자치구명', how='left')
        gdf['집객시설_수'] = gdf['집객시설_수'].fillna(0)
    except: pass

    # ==============================================================================
    # 3. 버스 데이터 (디버깅 강화)
    # ==============================================================================
    bus_file = './data/GGD_StationInfo_M.xlsx'
    if os.path.exists(bus_file):
        try:
            df_bus = pd.read_excel(bus_file)
            
            # (1) 컬럼 이름 자동 찾기 (X, Y, 경도, 위도 등)
            x_col = next((c for c in ['X', 'x', '경도', 'lon', 'LON'] if c in df_bus.columns), None)
            y_col = next((c for c in ['Y', 'y', '위도', 'lat', 'LAT'] if c in df_bus.columns), None)
            
            if x_col and y_col:
                df_bus = df_bus.dropna(subset=[x_col, y_col])
                
                # (2) 좌표계 확인 (중요!)
                # X좌표가 180보다 크다면(예: 200000), 위경도가 아님 -> 분석 불가
                if df_bus[x_col].iloc[0] > 180:
                    st.error(f"⚠️ [버스] 좌표계 오류: 파일의 좌표가 위도/경도가 아닙니다. (값 예시: {df_bus[x_col].iloc[0]})\nEPSG:4326(위경도) 좌표로 변환된 파일을 올려주세요.")
                    gdf['버스정류장_수'] = 0
                else:
                    geom = [Point(xy) for xy in zip(df_bus[x_col], df_bus[y_col])]
                    gdf_bus = geopandas.GeoDataFrame(df_bus, geometry=geom, crs="EPSG:4326")
                    joined = geopandas.sjoin(gdf_bus, gdf, how="inner", predicate="within")
                    
                    cnt = joined.groupby('자치구명').size().reset_index(name='버스정류장_수')
                    gdf = gdf.merge(cnt, on='자치구명', how='left')
                    gdf['버스정류장_수'] = gdf['버스정류장_수'].fillna(0)
            else:
                st.error(f"⚠️ [버스] 엑셀 파일에 'X', 'Y' 또는 '경도', '위도' 컬럼이 없습니다. (현재 컬럼: {list(df_bus.columns)})")
                gdf['버스정류장_수'] = 0
        except Exception as e:
            st.error(f"⚠️ [버스] 데이터 처리 중 에러: {e}")
            gdf['버스정류장_수'] = 0
    else:
        # st.warning("버스 데이터 파일(GGD_StationInfo_M.xlsx)이 없습니다.")
        gdf['버스정류장_수'] = 0

    gdf['버스 밀도'] = gdf['버스정류장_수'] / gdf['면적(km²)']

    # ==============================================================================
    # 4. 지하철 데이터 (디버깅 강화)
    # ==============================================================================
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
                
                # 좌표계 확인
                if df_sub[x_col].iloc[0] > 180:
                    st.error(f"⚠️ [지하철] 좌표계 오류: 좌표가 위도/경도가 아닙니다. (값 예시: {df_sub[x_col].iloc[0]})")
                    gdf['지하철역_수'] = 0
                else:
                    geom = [Point(xy) for xy in zip(df_sub[x_col], df_sub[y_col])]
                    gdf_sub = geopandas.GeoDataFrame(df_sub, geometry=geom, crs="EPSG:4326")
                    joined = geopandas.sjoin(gdf_sub, gdf, how="inner", predicate="within")
                    cnt = joined.groupby('자치구명').size().reset_index(name='지하철역_수')
                    gdf = gdf.merge(cnt, on='자치구명', how='left')
                    gdf['지하철역_수'] = gdf['지하철역_수'].fillna(0)
            else:
                st.error(f"⚠️ [지하철] 파일에 '경도/위도' 또는 'X/Y' 컬럼이 없습니다. (현재 컬럼: {list(df_sub.columns)})")
                gdf['지하철역_수'] = 0
        except Exception as e:
            st.error(f"⚠️ [지하철] 데이터 처리 중 에러: {e}")
            gdf['지하철역_수'] = 0
    else:
        # st.warning("지하철 데이터 파일이 없습니다.")
        gdf['지하철역_수'] = 0

    gdf['지하철 밀도'] = gdf['지하철역_수'] / gdf['면적(km²)']

    # -----------------------------------------------------------
    # 5. 교통 통계 및 단위 추가
    # -----------------------------------------------------------
    gdf['총_교통수단_수'] = gdf.get('버스정류장_수', 0) + gdf.get('지하철역_수', 0)
    pop_safe = gdf['총_상주인구_수'].replace(0, 1)
    gdf['인구 대비 교통수단 비율'] = gdf['총_교통수단_수'] / pop_safe
    gdf['교통 부족 순위'] = gdf['인구 대비 교통수단 비율'].rank(ascending=True, method='min')

    # 컬럼명 변경 (단위 추가)
    rename_map = {
        '총_상주인구_수': '총 상주인구 수 (명)',
        '집객시설_수': '집객시설 수 (개)',
        '버스정류장_수': '버스정류장 수 (개)',
        '지하철역_수': '지하철역 수 (개)',
        '면적(km²)': '면적 (km²)',
        '인구 밀도': '인구 밀도 (명/km²)',
        '버스 밀도': '버스 밀도 (개/km²)',
        '지하철 밀도': '지하철 밀도 (개/km²)',
        '인구 대비 교통수단 비율': '인구 대비 교통수단 비율 (개/명)',
        '교통 부족 순위': '교통 부족 순위 (위)'
    }
    gdf = gdf.rename(columns={k: v for k, v in rename_map.items() if k in gdf.columns})

    return gdf
