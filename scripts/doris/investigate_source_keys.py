"""Test plausible key/price explanations without modifying source records."""
import argparse
import json
from pathlib import Path
import duckdb

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',type=Path,default=ROOT/'target/data-audit/official.duckdb')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'reports/route-implementation/2026-10-04')
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(str(args.database));con.execute("SET memory_limit='4GB'");con.execute('SET threads=4')
    def rows(sql):
        cursor=con.execute(sql)
        return [dict(zip([column[0] for column in cursor.description],row)) for row in cursor.fetchall()]
    b='newzl.hsj_stock_hq_basic';e='newzl.hsj_stock_hq_ext'
    output={'purpose':'DIAGNOSTIC_HYPOTHESES_NOT_APPROVED_REPAIR','automaticDataCorrections':0}
    try:
        con.execute(f'CREATE OR REPLACE TEMP TABLE route_orphans AS SELECT e.* FROM {e} e ANTI JOIN {b} b USING(mktcode,tgtcode,bizdate)')
        output['orphanRows']=con.execute('SELECT COUNT(*) FROM route_orphans').fetchone()[0]
        output['nonCanonicalCodes']={table:rows(f"SELECT COUNT(*) FILTER(WHERE tgtcode!=TRIM(tgtcode)) whitespaceCodes,COUNT(*) FILTER(WHERE NOT regexp_full_match(tgtcode,'[0-9]{{6}}')) nonSixDigitCodes FROM newzl.{table}")[0] for table in ('hsj_stock_code_info','hsj_stock_hq_basic','hsj_stock_hq_ext')}
        output['sameCodeDateOtherMarket']=rows(f'SELECT COUNT(*) n FROM route_orphans e SEMI JOIN {b} b ON e.tgtcode=b.tgtcode AND e.bizdate=b.bizdate AND e.mktcode!=b.mktcode')[0]['n']
        output['numericCodeEquivalentSameDate']=rows(f'SELECT COUNT(*) n FROM route_orphans e SEMI JOIN {b} b ON e.mktcode=b.mktcode AND TRY_CAST(e.tgtcode AS BIGINT)=TRY_CAST(b.tgtcode AS BIGINT) AND e.bizdate=b.bizdate')[0]['n']
        output['calendarDateOffsets']=[]
        for offset in (-3,-2,-1,1,2,3):
            count=rows(f"SELECT COUNT(*) n FROM route_orphans e SEMI JOIN {b} b ON e.mktcode=b.mktcode AND e.tgtcode=b.tgtcode AND b.bizdate=e.bizdate+INTERVAL '{offset} DAY'")[0]['n']
            output['calendarDateOffsets'].append({'basicDateMinusExtensionDate':offset,'candidateMatches':count})
        output['priceCategories']=rows(f"""SELECT CASE WHEN highPx=0 OR lowPx=0 THEN 'ZERO_RANGE_ENDPOINT'
            WHEN highPx=lowPx THEN 'FLAT_RANGE' ELSE 'NONZERO_NONFLAT_RANGE' END category,
            COUNT(*) n,MIN(bizdate) firstDate,MAX(bizdate) lastDate,
            COUNT(*) FILTER(WHERE closePx=lastPx) closeEqualsLast,
            MIN(CASE WHEN closePx>highPx THEN closePx-highPx ELSE lowPx-closePx END) minimumRawDeviation,
            MAX(CASE WHEN closePx>highPx THEN closePx-highPx ELSE lowPx-closePx END) maximumRawDeviation
            FROM {b} WHERE closePx>highPx OR closePx<lowPx GROUP BY category ORDER BY category""")
        output['priceByYear']=rows(f'SELECT YEAR(bizdate) auditYear,COUNT(*) n FROM {b} WHERE closePx>highPx OR closePx<lowPx GROUP BY auditYear ORDER BY auditYear')
        output['priceExamples']=rows(f"SELECT mktcode,tgtcode,bizdate,openPx,highPx,lowPx,closePx,lastPx,volume,turnover,qfqMulti,qfqAdd,hfqMulti,hfqAdd FROM {b} WHERE closePx>highPx OR closePx<lowPx ORDER BY CASE WHEN closePx>highPx THEN closePx-highPx ELSE lowPx-closePx END DESC LIMIT 30")
        output['conclusions']=[
            'An offset candidate is not evidence that a date shift is valid: ordinary neighbouring trading rows also match.',
            'No missing key or price is changed; original relationship and price warnings remain.',
            'Official field definitions or corrected files are required to select a data repair rule.']
        print('Source hypothesis investigation complete',flush=True)
    finally:
        con.close()
        (args.output_dir/'source-hypotheses.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')


if __name__=='__main__':main()
