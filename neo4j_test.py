import json
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()  # .env 파일 로드

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER")
PASSWORD = os.getenv("NEO4J_PASSWORD")

# 1. 드라이버 생성 (VM IP와 Bolt 포트 7687 사용)
AUTH = (USER, PASSWORD) # Neo4j 계정 정보

def migrate_data(tx, data):
    # JSON 최상단에서 books_id와 기본 정보 추출
    book_id = str(data["books_id"])
    book_title = "데미안"  # 필요 시 책 마스터 타이틀 정의
    
    for row in data["results"]:
        chapter_id = str(row["chapter_id"])
        chapter_title = row["chapter_title"]
        
        # [Step 1] 도서 - 챕터 관계 연결 (계층 구조 출발점 형성)
        tx.run("""
            MERGE (b:Book {books_id: $book_id})
            ON CREATE SET b.title = $book_title
            MERGE (ch:Chapter {chapter_id: $chapter_id})
            SET ch.title = $chapter_title
            MERGE (b)-[:HAS_CHAPTER]->(ch)
        """, book_id=book_id, book_title=book_title, chapter_id=chapter_id, chapter_title=chapter_title)
        
        contents = row["result"]
        
        # [Step 2] 인물(Character) 노드 생성
        for char in contents["characters"]:
            # 이름_책ID 구조로 노드 고유 ID 파생 생성 (RDB와 완벽 동기화 대용)
            char_id = f"{char['name']}_{book_id}"
            tx.run("""
                MERGE (c:Character {character_id: $char_id})
                SET c.character_name = $name, c.role = $role, c.description = $description
            """, char_id=char_id, name=char["name"], role=char["role"], description=char["description"])
            
        # [Step 3] 사건(Event) 노드 생성 및 관계 연결
        for idx, ev in enumerate(contents["events"]):
            event_id = f"ev_{chapter_id}_{idx}"  # 사건 고유 ID 조립
            
            # 3-1. 챕터 -> 사건 연결
            tx.run("""
                MATCH (ch:Chapter {chapter_id: $chapter_id})
                MERGE (e:Event {event_id: $event_id})
                SET e.summary = $summary, e.start_paragraph_order = $start_para, e.end_paragraph_order = $end_para
                MERGE (ch)-[:HAS_EVENT]->(e)
            """, chapter_id=chapter_id, event_id=event_id, summary=ev["summary"], 
                 start_para=ev["start_paragraph_order"], end_para=ev["end_paragraph_order"])
            
            # 3-2. 사건 -> 참여 인물(INVOLVES) 연결
            for ev_char in ev["characters"]:
                target_char_id = f"{ev_char['name']}_{book_id}"
                tx.run("""
                    MATCH (e:Event {event_id: $event_id})
                    MATCH (c:Character {character_id: $char_id})
                    MERGE (e)-[r:INVOLVES]->(c)
                    SET r.role_in_event = $role_in_event
                """, event_id=event_id, char_id=target_char_id, role_in_event=ev_char["role_in_event"])
                
        # [Step 4] 인물 간 관계 변동 이력 (RELATES_TO) 연결
        for r_idx, rel in enumerate(contents["relationships"]):
            src_id = f"{rel['source']}_{book_id}"
            tgt_id = f"{rel['target']}_{book_id}"
            rel_change_id = f"rc_{chapter_id}_{r_idx}"
            
            tx.run("""
                MATCH (c1:Character {character_id: $src_id})
                MATCH (c2:Character {character_id: $tgt_id})
                MERGE (c1)-[r:RELATES_TO]->(c2)
                SET r.relationship_change_id = $rel_change_id,
                    r.new_relation = $relation,
                    r.change_reason = $change_summary,
                    r.evidence = $evidence,
                    r.start_paragraph_order = $start_para,
                    r.end_paragraph_order = $end_para
            """, src_id=src_id, tgt_id=tgt_id, rel_change_id=rel_change_id,
                 relation=rel["relation"], change_summary=rel["change_summary"], evidence=rel["evidence"],
                 start_para=rel["start_paragraph_order"], end_para=rel["end_paragraph_order"])

# 🚀 메인 실행 로직
if __name__ == "__main__":
    file_path = "input.json"
    
    # input.json 파일이 있는지 안전하게 체크 후 로드
    if not os.path.exists(file_path):
        print(f"❌ 에러: {file_path} 파일이 현재 경로에 없습니다. 확인해 주세요!")
    else:
        print(f"📦 {file_path} 파일을 로드하는 중...")
        with open(file_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)
            
        print("🔗 Neo4j 드라이버 연결 및 데이터 적재 시도 중...")
        driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
        try:
            with driver.session() as session:
                session.execute_write(migrate_data, json_data)
            print("🎉 축하합니다! input.json 기반 그래프 적재가 완벽히 성공했습니다!")
        except Exception as e:
            print(f"❌ 데이터 적재 중 에러 발생: {str(e)}")
        finally:
            driver.close()