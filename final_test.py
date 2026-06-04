import json
import os
import psycopg2
from dotenv import load_dotenv
from neo4j import GraphDatabase
from psycopg2.extras import RealDictCursor

# 1. .env 파일 로드
load_dotenv()

# 2. 환경 변수 세팅
PG_HOST = os.getenv("DB_HOST")
PG_NAME = os.getenv("DB_NAME")
PG_USER = os.getenv("DB_USER")
PG_PASSWORD = os.getenv("DB_PASSWORD")
PG_PORT = os.getenv("DB_PORT", 5432)

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


# =====================================================================
# [Step 1] 🛠️ 4개 정규화 테이블 데이터 추출 및 Neo4j 규격 결합 함수
# =====================================================================
def fetch_and_transform_postgres_data(target_books_id):
    pg_config = {
        "host": PG_HOST,
        "database": PG_NAME,
        "user": PG_USER,
        "password": PG_PASSWORD,
        "port": PG_PORT,
    }

    try:
        connection = psycopg2.connect(**pg_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        # -------------------------------------------------------------
        # 1-1. 인물(character) 테이블 조회
        # -------------------------------------------------------------
        char_query = """
            SELECT character_id, character_name, role, description 
            FROM readpoint.character 
            WHERE books_id = %s;
        """
        cursor.execute(char_query, (target_books_id,))
        characters_rows = cursor.fetchall()

        if not characters_rows:
            print(f"⚠️ PostgreSQL에 도서 ID '{target_books_id}'로 조회된 인물 정보가 없습니다.")
            return None

        # ID 기반 데이터를 이름 매핑 문자열로 번역하기 위한 변환 매핑 사전 구축
        char_name_map = {c["character_id"]: c["character_name"] for c in characters_rows}

        # -------------------------------------------------------------
        # 1-2. 사건(event) 테이블 조회
        # -------------------------------------------------------------
        event_query = """
            SELECT event_id, chapter_id, event_order, summary, evidence, 
                   start_paragraph_id, end_paragraph_id, short_title
            FROM readpoint.event
            WHERE books_id = %s
            ORDER BY chapter_id ASC, event_order ASC;
        """
        cursor.execute(event_query, (target_books_id,))
        event_rows = cursor.fetchall()

        # -------------------------------------------------------------
        # 1-3. 사건별 인물 매핑(event_character) 테이블 조회 (INNER JOIN 필수)
        # -------------------------------------------------------------
        ev_char_query = """
            SELECT ec.event_id, ec.character_id, ec.role_in_event
            FROM readpoint.event_character ec
            INNER JOIN readpoint.event e ON ec.event_id = e.event_id
            WHERE e.books_id = %s;
        """
        cursor.execute(ev_char_query, (target_books_id,))
        ev_char_rows = cursor.fetchall()

        # event_id 별로 참여 인물들을 묶어줄 매핑 딕셔너리 생성
        ev_char_map = {}
        for ec in ev_char_rows:
            ev_id = ec["event_id"]
            if ev_id not in ev_char_map:
                ev_char_map[ev_id] = []
            
            c_id = ec["character_id"]
            c_name = char_name_map.get(c_id, f"Unknown_{c_id}")
            ev_char_map[ev_id].append({
                "name": c_name,
                "role_in_event": ec["role_in_event"]
            })

        # -------------------------------------------------------------
        # 1-4. 관계 변동 이력(relationship_change) 테이블 조회
        # -------------------------------------------------------------
        rel_query = """
            SELECT chapter_id, source_character_id, target_character_id, 
                   relation, change_summary, evidence, start_paragraph_order, end_paragraph_order
            FROM readpoint.relationship_change
            WHERE books_id = %s;
        """
        cursor.execute(rel_query, (target_books_id,))
        rel_rows = cursor.fetchall()

        # -------------------------------------------------------------
        # ⚙️ [트리 구조 데이터 조립]
        # -------------------------------------------------------------
        combined_data = {"books_id": str(target_books_id), "results": []}
        chapters_map = {}

        # 챕터별로 사건 및 공통 캐릭터 데이터 기본 뼈대 안착
        for idx, ev in enumerate(event_rows):
            ch_id = str(ev["chapter_id"])

            if ch_id not in chapters_map:
                chapters_map[ch_id] = {
                    "chapter_id": ch_id,
                    "chapter_order": idx + 1,        # 챕터 순서 정보 임시 대체 기입
                    "chapter_title": f"{ch_id} 챕터", # 챕터 타이틀 정보 임시 대체 기입
                    "result": {
                        "characters": [
                            {
                                "name": c["character_name"],
                                "role": c["role"],
                                "description": c["description"],
                            }
                            for c in characters_rows
                        ]
                    },
                    "events_list": [],
                    "relationships_list": [],
                }

            # 이 사건에 속한 인물 목록 조회 및 주입
            linked_characters = ev_char_map.get(ev["event_id"], [])

            event_item = {
                "summary": ev["summary"],
                "start_paragraph_order": ev["start_paragraph_id"],
                "end_paragraph_order": ev["end_paragraph_id"],
                "characters": linked_characters,
            }
            chapters_map[ch_id]["events_list"].append(event_item)

        # 관계 변동 데이터를 각 챕터별 맵에 매핑 (ID를 이름 문자열로 치환)
        for rel in rel_rows:
            ch_id = str(rel["chapter_id"])
            if ch_id in chapters_map:
                src_name = char_name_map.get(rel["source_character_id"], "Unknown")
                tgt_name = char_name_map.get(rel["target_character_id"], "Unknown")

                rel_item = {
                    "source": src_name,
                    "target": tgt_name,
                    "relation": rel["relation"],
                    "change_summary": rel["change_summary"],
                    "evidence": rel["evidence"],
                    "start_paragraph_order": rel["start_paragraph_order"],
                    "end_paragraph_order": rel["end_paragraph_order"],
                }
                chapters_map[ch_id]["relationships_list"].append(rel_item)

        # 딕셔너리 구조를 최종 반환을 위한 리스트 객체로 재변환
        for ch_data in chapters_map.values():
            chapter_final = {
                "chapter_id": ch_data["chapter_id"],
                "chapter_order": ch_data["chapter_order"],
                "chapter_title": ch_data["chapter_title"],
                "result": {
                    "characters": ch_data["result"]["characters"],
                    "events": ch_data["events_list"],
                    "relationships": ch_data["relationships_list"],
                },
            }
            combined_data["results"].append(chapter_final)

        return combined_data

    except Exception as e:
        print(f"❌ PostgreSQL 데이터 조회/변환 실패: {str(e)}")
        return None
    finally:
        if "cursor" in locals() and cursor:
            cursor.close()
        if "connection" in locals() and connection:
            connection.close()


# =====================================================================
# [Step 2] 🕸️ Neo4j 실시간 시계열 그래프 데이터 적재 트랜잭션 함수
# =====================================================================
def migrate_data(tx, data):
    book_id = str(data["books_id"])

    for row in data["results"]:
        chapter_id = str(row["chapter_id"])
        chapter_order = row["chapter_order"]
        chapter_title = row["chapter_title"]

        # 1. 도서 - 챕터 관계 연결
        tx.run(
            """
            MERGE (b:Book {books_id: $book_id})
            MERGE (ch:Chapter {chapter_id: $chapter_id})
            SET ch.title = $chapter_title, ch.chapter_order = $chapter_order
            MERGE (b)-[:HAS_CHAPTER]->(ch)
            """,
            book_id=book_id,
            chapter_id=chapter_id,
            chapter_order=chapter_order,
            chapter_title=chapter_title,
        )

        contents = row["result"]

        # 2. 인물(Character) 노드 생성
        for char in contents.get("characters", []):
            char_id = f"{char['name']}_{book_id}"
            tx.run(
                """
                MERGE (c:Character {character_id: $char_id})
                SET c.character_name = $name, c.role = $role, c.description = $description
                """,
                char_id=char_id,
                name=char["name"],
                role=char.get("role"),
                description=char.get("description"),
            )

        # 3. 사건(Event) 노드 생성 및 관계 연결
        for idx, ev in enumerate(contents.get("events", [])):
            event_id = f"ev_{chapter_id}_{idx}"

            # 3-1. 챕터 -> 사건 연결
            tx.run(
                """
                MATCH (ch:Chapter {chapter_id: $chapter_id})
                MERGE (e:Event {event_id: $event_id})
                SET e.summary = $summary, e.start_paragraph_order = $start_para, e.end_paragraph_order = $end_para
                MERGE (ch)-[:HAS_EVENT]->(e)
                """,
                chapter_id=chapter_id,
                event_id=event_id,
                summary=ev.get("summary"),
                start_para=ev.get("start_paragraph_order"),
                end_para=ev.get("end_paragraph_order"),
            )

            # 3-2. 사건 -> 참여 인물(INVOLVES) 연결
            for ev_char in ev.get("characters", []):
                target_char_id = f"{ev_char['name']}_{book_id}"
                tx.run(
                    """
                    MATCH (e:Event {event_id: $event_id})
                    MATCH (c:Character {character_id: $char_id})
                    MERGE (e)-[r:INVOLVES]->(c)
                    SET r.role_in_event = $role_in_event
                    """,
                    event_id=event_id,
                    char_id=target_char_id,
                    role_in_event=ev_char.get("role_in_event"),
                )

        # 4. 인물 간 관계 변동 이력 (RELATES_TO) 연결 (시계열 누적)
        for r_idx, rel in enumerate(contents.get("relationships", [])):
            src_id = f"{rel['source']}_{book_id}"
            tgt_id = f"{rel['target']}_{book_id}"
            rel_change_id = f"rc_{chapter_id}_{r_idx}"

            tx.run(
                """
                MATCH (c1:Character {character_id: $src_id})
                MATCH (c2:Character {character_id: $tgt_id})
                
                MERGE (c1)-[r:RELATES_TO {chapter_id: $chapter_id}]->(c2)
                SET r.relationship_change_id = $rel_change_id,
                    r.chapter_order = $chapter_order,
                    r.new_relation = $relation,
                    r.change_reason = $change_summary,
                    r.evidence = $evidence,
                    r.start_paragraph_order = $start_para,
                    r.end_paragraph_order = $end_para
                """,
                src_id=src_id,
                tgt_id=tgt_id,
                chapter_id=chapter_id,
                chapter_order=chapter_order,
                rel_change_id=rel_change_id,
                relation=rel.get("relation"),
                change_summary=rel.get("change_summary"),
                evidence=rel.get("evidence"),
                start_para=rel.get("start_paragraph_order"),
                end_para=rel.get("end_paragraph_order"),
            )


# =====================================================================
# 🚀 메인 실행 프로세스 엔트리포인트
# =====================================================================
if __name__ == "__main__":
    # 데이터베이스 마이그레이션 대상이 될 books_id를 정의합니다.
    target_id = 1 

    print(f"📦 [1/2] PostgreSQL 정규화 구조 테이블에서 도서 ID '{target_id}' 데이터 추출 및 병합 처리 중...")
    json_data = fetch_and_transform_postgres_data(target_id)

    if json_data:
        print(f"🔗 [2/2] Neo4j DB 드라이버 바인딩 및 시계열 그래프 파이프라인 적재 시작...")
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        try:
            with driver.session() as session:
                session.execute_write(migrate_data, json_data)
            print(f"🎉 성공: 도서 ID '{target_id}'의 PostgreSQL ➡️ Neo4j 마이그레이션이 성공적으로 완수되었습니다!")
        except Exception as e:
            print(f"❌ Neo4j 적재 트랜잭션 에러 발생: {str(e)}")
        finally:
            driver.close()
    else:
        print("❌ 에러: 원천 데이터를 수집 및 조립하지 못하여 마이그레이션을 조기 종료합니다.")