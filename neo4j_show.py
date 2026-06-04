import builtins
from functools import partial
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
from pyvis.network import Network  # 👈 웹 시각화 라이브러리

# .env 로드 및 Neo4j 연결
load_dotenv()
URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER")
PASSWORD = os.getenv("NEO4J_PASSWORD")

driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))


def generate_web_graph_by_chapter(book_id, chapter_id):
    # 💡 [쿼리 보정] 다른 책의 인물 데이터와 혼선이 생기지 않도록 r.chapter_id 조건 및 중복 제거 강화
    query = """
    MATCH (b:Book {books_id: $book_id})-[:HAS_CHAPTER]->(ch:Chapter {chapter_id: $chapter_id})
    MATCH (c1:Character)-[r:RELATES_TO {chapter_id: ch.chapter_id}]->(c2:Character)
    WHERE c1.character_id ENDS WITH "_" + $book_id 
      AND c2.character_id ENDS WITH "_" + $book_id
    
    RETURN DISTINCT 
           c1.character_name AS src, c1.role AS src_role,
           c2.character_name AS tgt, c2.role AS tgt_role,
           r.new_relation AS rel, r.change_reason AS reason
    """

    # 2. Pyvis 네트워크 객체 생성
    net = Network(
        height="800px",
        width="100%",
        bgcolor="#222222",
        font_color="white",
        directed=True,
    )
    net.barnes_hut()  # 쫀득하게 움직이는 물리 엔진 활성화

    seen_edges = set()

    with driver.session() as session:
        result = session.run(
            query, book_id=str(book_id), chapter_id=str(chapter_id)
        )

        edge_count = 0

        for record in result:
            src = record["src"]
            tgt = record["tgt"]
            rel = record["rel"]
            reason = record["reason"]

            edge_key = (src, tgt, rel)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edge_count += 1

            # 3. 출발 노드 추가 (비어있을 수 있는 role 방어 코드 포함)
            src_role = record["src_role"] if record["src_role"] else "기록 없음"
            src_hover = f"<b>{src}</b><br>역할: {src_role}"
            net.add_node(
                src, label=src, title=src_hover, color="#ff7675", size=25
            )

            # 4. 도착 노드 추가
            tgt_role = record["tgt_role"] if record["tgt_role"] else "기록 없음"
            tgt_hover = f"<b>{tgt}</b><br>역할: {tgt_role}"
            net.add_node(
                tgt, label=tgt, title=tgt_hover, color="#74b9ff", size=25
            )

            # 5. 관계 선(Edge) 잇기
            edge_hover = f"<b>{rel}</b><br>{reason}"
            net.add_edge(
                src, tgt, label=rel, title=edge_hover, color="#ffeaa7", width=2
            )

    if edge_count == 0:
        print(
            f"⚠️ 주의: 책 {book_id}의 챕터 {chapter_id}에는 기록된 인물 관계 데이터가 없습니다."
        )
        return

    # 💡 인코딩 에러(cp949)와 빈 화면 버그를 동시에 깨부수는 저장 로직
    output_filename = f"book_{book_id}_chapter_{chapter_id}_relations.html"

    # 찰나의 순간에 open 함수를 utf-8 전용으로 속여서 pyvis 고유의 데이터 조립 프로세스를 태웁니다.
    original_open = builtins.open
    builtins.open = partial(original_open, encoding="utf-8")

    try:
        net.save_graph(output_filename)
    finally:
        builtins.open = original_open  # 원상 복구

    print(
        f"🎯 웹 관계도 생성 완료! '{output_filename}' 파일을 브라우저로 확인하세요."
    )


if __name__ == "__main__":
    try:
        target_book = 1

        # 1. 먼저 해당 책에 어떤 챕터들이 있는지 DB에서 챕터 리스트를 긁어옵니다.
        find_chapters_query = """
        MATCH (b:Book {books_id: $book_id})-[:HAS_CHAPTER]->(ch:Chapter)
        RETURN ch.chapter_id AS ch_id
        ORDER BY ch.chapter_order ASC
        """

        with driver.session() as session:
            chapters = session.run(find_chapters_query, book_id=str(target_book))
            chapter_ids = [row["ch_id"] for row in chapters]

        # 2. 존재하는 챕터 수만큼 돌면서 HTML 파일들을 연속으로 생성합니다.
        if not chapter_ids:
            print(
                f"❌ 에러: Neo4j에서 책 ID {target_book}번에 해당하는 챕터를 찾지 못했습니다."
            )
        else:
            print(
                f"총 {len(chapter_ids)}개의 챕터를 발견했습니다. 시각화 생성을 시작합니다."
            )
            for ch_id in chapter_ids:
                generate_web_graph_by_chapter(
                    book_id=target_book, chapter_id=ch_id
                )

    finally:
        driver.close()