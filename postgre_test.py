import json
import os
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

# 1. .env 파일의 내용을 환경 변수로 로드합니다.
load_dotenv()
def fetch_chapter_analysis(target_books_id: int):
    # 2. os.environ.get()을 이용해 기존 환경 변수 키값(DB_HOST 등)을 그대로 가져옵니다.
    connection_config = {
        "host": os.environ.get("DB_HOST"),
        "database": os.environ.get("DB_NAME"),
        "user": os.environ.get("DB_USER"),
        "password": os.environ.get("DB_PASSWORD"),
        "port": os.environ.get("DB_PORT", 5432),
    }

    try:
        # 데이터베이스 연결
        connection = psycopg2.connect(**connection_config)
        cursor = connection.cursor(cursor_factory=RealDictCursor)

        # -------------------------------------------------------------
        # 1. 인물(character) 테이블 조회
        # -------------------------------------------------------------
        char_query = """
            SELECT character_id, character_name, role, description 
            FROM readpoint.character 
            WHERE books_id = %s;
        """
        cursor.execute(char_query, (target_books_id,))
        characters_rows = cursor.fetchall()

        if not characters_rows:
            print(
                f"⚠️ 도서 ID '{target_books_id}'에 해당하는 인물 정보가 없습니다."
            )
            return None

        # Neo4j ID 생성을 위해 character_id 빌드용 매핑 딕셔너리 생성
        # 구조: { character_id: "인물 이름" }
        char_name_map = {
            c["character_id"]: c["character_name"] for c in characters_rows
        }

        # -------------------------------------------------------------
        # 2. 사건(event) 테이블 조회
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
        # 3. 사건별 인물 매핑(event_character) 테이블 조회
        # -------------------------------------------------------------
        # 💡 [핵심] event_character는 books_id가 없으므로 event 테이블과 JOIN하여 긁어옵니다.
        ev_char_query = """
            SELECT ec.event_id, ec.character_id, ec.role_in_event
            FROM readpoint.event_character ec
            INNER JOIN readpoint.event e ON ec.event_id = e.event_id
            WHERE e.books_id = %s;
        """
        cursor.execute(ev_char_query, (target_books_id,))
        ev_char_rows = cursor.fetchall()

        # event_id 별로 데이터를 딕셔너리에 묶어서 보관
        ev_char_map = {}
        for ec in ev_char_rows:
            ev_id = ec["event_id"]
            if ev_id not in ev_char_map:
                ev_char_map[ev_id] = []

            # ID를 기반으로 실제 인물 이름을 매핑 테이블에서 매칭
            c_id = ec["character_id"]
            c_name = char_name_map.get(c_id, f"Unknown_{c_id}")

            ev_char_map[ev_id].append(
                {"name": c_name, "role_in_event": ec["role_in_event"]}
            )

        # -------------------------------------------------------------
        # 4. 관계 변동 이력(relationship_change) 테이블 조회
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
        # ⚙️ [데이터 구조 조립] Neo4j 규격에 맞게 트리 구조로 조립
        # -------------------------------------------------------------
        combined_data = {"books_id": str(target_books_id), "results": []}
        chapters_map = {}

        # 사건 데이터를 순회하며 챕터별로 그룹화
        # 💡 진짜 구조에 맞춰 챕터 순서와 제목은 ID를 우선 가공하여 넣습니다.
        for idx, ev in enumerate(event_rows):
            ch_id = str(ev["chapter_id"])

            if ch_id not in chapters_map:
                chapters_map[ch_id] = {
                    "chapter_id": ch_id,
                    "chapter_order": idx + 1,  # 임시 순서값 부여
                    "chapter_title": f"{ch_id} 챕터",  # 임시 타이틀 부여
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

            # 이 사건에 참여한 인물 매핑 리스트 가져오기
            linked_characters = ev_char_map.get(ev["event_id"], [])

            event_item = {
                "summary": ev["summary"],
                "start_paragraph_order": ev["start_paragraph_id"],  # 스펙 명칭 매칭
                "end_paragraph_order": ev["end_paragraph_id"],  # 스펙 명칭 매칭
                "characters": linked_characters,
            }
            chapters_map[ch_id]["events_list"].append(event_item)

        # 관계 변동 데이터를 알맞은 챕터 맵에 매핑
        for rel in rel_rows:
            ch_id = str(rel["chapter_id"])
            if ch_id in chapters_map:
                src_name = char_name_map.get(
                    rel["source_character_id"], "Unknown"
                )
                tgt_name = char_name_map.get(
                    rel["target_character_id"], "Unknown"
                )

                rel_item = {
                    "source": src_name,  # Neo4j는 이름 기반 매핑을 하고 있으므로 매칭
                    "target": tgt_name,
                    "relation": rel["relation"],
                    "change_summary": rel["change_summary"],
                    "evidence": rel["evidence"],
                    "start_paragraph_order": rel["start_paragraph_order"],
                    "end_paragraph_order": rel["end_paragraph_order"],
                }
                chapters_map[ch_id]["relationships_list"].append(rel_item)

        # 딕셔너리로 임시 정렬했던 챕터 데이터를 리스트 형태로 최종 변환
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

        # 💡 터미널에 가독성 좋게 포매팅된 트리형 JSON 출력
        print("🎉 [성공] 진짜 테이블 구조에 맞춰 조립 완료된 JSON 데이터:")
        print(json.dumps(combined_data, ensure_ascii=False, indent=2))

        return combined_data

    except Exception as error:
        print(f"❌ 데이터베이스 오류 발생: {error}")
        raise error

    finally:
        if "cursor" in locals() and cursor:
            cursor.close()
        if "connection" in locals() and connection:
            connection.close()
            print("PostgreSQL 연결이 안전하게 종료되었습니다.")


if __name__ == "__main__":
    # 로컬에서 즉시 조회 및 변환을 테스트하고 싶은 도서 ID를 입력합니다.
    test_book_id = 1
    data = fetch_chapter_analysis(test_book_id)