from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()  # .env 파일 로드

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER")
PASSWORD = os.getenv("NEO4J_PASSWORD")


# 1. 드라이버 생성 (VM IP와 Bolt 포트 7687 사용)
URI = "neo4j://20.196.153.46:7687"
AUTH = (USER, PASSWORD) # Neo4j 계정 정보

def create_and_read_data():
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            
            # [입력] 데이터 추가 (Cypher 쿼리)
            # User 노드를 생성하고 name과 role 속성을 부여
            session.run(
                "CREATE (u:Test {name: $name, role: $role})",
                name="홍길동", role="Developer"
            )
            print("데이터 입력 완료!")

            # [조회] 데이터 검색
            # name이 '홍길동'인 노드를 찾아 반환
            result = session.run(
                "MATCH (u:Test {name: $name}) RETURN u.name AS name, u.role AS role",
                name="홍길동"
            )
            
            print("--- 조회 결과 ---")
            for record in result:
                print(f"이름: {record['name']}, 직무: {record['role']}")

if __name__ == "__main__":
    create_and_read_data()