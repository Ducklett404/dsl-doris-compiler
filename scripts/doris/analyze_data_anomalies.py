"""Explain audit failures without altering or silently filtering source data."""
import json
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[2]
con = duckdb.connect(str(ROOT / "target/data-audit/official.duckdb"))
con.execute("SET memory_limit='4GB'")
con.execute("SET threads=4")


def rows(sql):
    cursor = con.execute(sql)
    return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]


try:
    con.execute("""CREATE OR REPLACE TABLE audit_orphan_extension AS
        SELECT e.* FROM newzl.hsj_stock_hq_ext e ANTI JOIN newzl.hsj_stock_hq_basic b
        ON e.mktcode=b.mktcode AND e.tgtcode=b.tgtcode AND e.bizdate=b.bizdate""")
    report = {
        "status": "SOURCE_ISSUES_REQUIRE_REVIEW",
        "classificationBasis": "Calendar comparisons use dates actually observed in the basic table, not an official exchange calendar.",
        "orphanByYearMarket": rows("SELECT YEAR(bizdate) AS auditYear,mktcode,COUNT(*) n FROM audit_orphan_extension GROUP BY ALL ORDER BY auditYear,mktcode"),
        "orphanByWeekday": rows("SELECT DAYOFWEEK(bizdate) weekdaySunday0,COUNT(*) n FROM audit_orphan_extension GROUP BY ALL ORDER BY weekdaySunday0"),
        "orphanTopDates": rows("SELECT bizdate,COUNT(*) n FROM audit_orphan_extension GROUP BY bizdate ORDER BY n DESC,bizdate LIMIT 20"),
        "orphanTopSecurities": rows("SELECT e.mktcode,e.tgtcode,c.name,COUNT(*) n,MIN(bizdate) firstDate,MAX(bizdate) lastDate FROM audit_orphan_extension e LEFT JOIN newzl.hsj_stock_code_info c USING(mktcode,tgtcode) GROUP BY ALL ORDER BY n DESC,e.mktcode,e.tgtcode LIMIT 20"),
        "orphansNotOnAnyObservedMarketDate": rows("SELECT COUNT(*) n FROM audit_orphan_extension e ANTI JOIN (SELECT DISTINCT mktcode,bizdate FROM newzl.hsj_stock_hq_basic) c USING(mktcode,bizdate)"),
        "orphansRelativeToBasicSpan": rows("""WITH spans AS (SELECT mktcode,tgtcode,MIN(bizdate) firstDate,MAX(bizdate) lastDate FROM newzl.hsj_stock_hq_basic GROUP BY ALL)
            SELECT CASE WHEN s.tgtcode IS NULL THEN 'NO_BASIC_HISTORY' WHEN e.bizdate<s.firstDate THEN 'BEFORE_FIRST_BASIC'
                WHEN e.bizdate>s.lastDate THEN 'AFTER_LAST_BASIC' ELSE 'WITHIN_BASIC_SPAN' END classification,COUNT(*) n
            FROM audit_orphan_extension e LEFT JOIN spans s USING(mktcode,tgtcode) GROUP BY classification ORDER BY classification"""),
        "latestDateOrphans": rows("SELECT mktcode,tgtcode,bizdate,ZJLXMainNetTur FROM audit_orphan_extension WHERE bizdate=DATE '2026-04-14' ORDER BY mktcode,tgtcode"),
        "closeOutsideRange": rows("SELECT mktcode,tgtcode,bizdate,openPx,highPx,lowPx,closePx FROM newzl.hsj_stock_hq_basic WHERE closePx>highPx OR closePx<lowPx ORDER BY mktcode,tgtcode,bizdate LIMIT 100"),
        "missingSecurityHistory": rows("SELECT c.mktcode,c.tgtcode,c.name FROM newzl.hsj_stock_code_info c ANTI JOIN (SELECT DISTINCT mktcode,tgtcode FROM newzl.hsj_stock_hq_basic) b USING(mktcode,tgtcode) ORDER BY mktcode,tgtcode"),
    }
    output = ROOT / "reports/data-inspection/2026-10-04/数据异常定位.json"
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
    con.execute("COPY (SELECT mktcode,tgtcode,bizdate,ZJLXMainNetTur FROM audit_orphan_extension ORDER BY mktcode,tgtcode,bizdate) TO ? (HEADER, DELIMITER ',')", [str(ROOT / "target/data-audit/orphan-extension-keys.csv")])
    print(json.dumps({key: report[key] for key in ['orphanByWeekday','orphansNotOnAnyObservedMarketDate','orphansRelativeToBasicSpan']},ensure_ascii=False,indent=2))
finally:
    con.close()
