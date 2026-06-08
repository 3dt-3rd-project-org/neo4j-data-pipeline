// 사용법: :params {books_id: "1", target_chapter: "3", target_para: 10}
// 아래 쿼리를 복사하여 실행하세요.

MATCH (src:Character)-[r:RELATES_TO]->(tgt:Character)
WHERE src.character_id ENDS WITH ("_" + $books_id)
  AND (
    toInteger(r.chapter_id) < toInteger($target_chapter)
    OR (toInteger(r.chapter_id) = toInteger($target_chapter)
        AND toInteger(r.start_paragraph_order) <= toInteger($target_para))
  )
WITH src, tgt, r
ORDER BY toInteger(r.chapter_id) ASC, toInteger(r.start_paragraph_order) ASC
WITH src, tgt, collect(r) AS rels
WITH src, tgt, rels[size(rels)-1] AS latest_r
OPTIONAL MATCH (e:Event)
WHERE e.chapter_id = latest_r.chapter_id
  AND toInteger(e.start_paragraph_order) >= toInteger(latest_r.start_paragraph_order)
  AND toInteger(e.start_paragraph_order) <= toInteger(latest_r.end_paragraph_order)
RETURN src.character_name AS src,
       tgt.character_name AS tgt,
       latest_r.new_relation AS rel,
       latest_r.change_reason AS reason,
       latest_r.chapter_id AS chapter,
       latest_r.start_paragraph_order AS para
ORDER BY toInteger(chapter) ASC, toInteger(para) ASC;