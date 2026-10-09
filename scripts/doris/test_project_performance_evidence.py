from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from check_project_performance_evidence import stats,summarize,verify_compiler


class PerformanceContracts(unittest.TestCase):
    def test_nearest_rank_does_not_average_the_p95_tail(self):
        self.assertEqual(dict(samples=30,p50=15,p95=29,max=30),stats(list(range(1,31))))

    def test_invalid_samples_rejected(self):
        for samples in ([],[-1],[float('nan')],[float('inf')],[True],['1']):
            with self.subTest(samples=samples),self.assertRaises(ValueError):stats(samples)

    def compiler(self):
        return dict(warmupIterations=1000,uncachedPipeline=dict(iterations=5000,
            stages={k:dict(p50=.1,p95=.2,p99=.3,max=1.) for k in ('parse','semantic','rewrite','planning','sqlGeneration','total')}))

    def test_complex_compiler_report_contract(self):
        self.assertEqual(.2,verify_compiler(self.compiler()))
        for value in (50,51,-1,float('nan'),float('inf')):
            data=self.compiler();data['uncachedPipeline']['stages']['total']['p95']=value
            with self.subTest(value=value),self.assertRaises(ValueError):verify_compiler(data)
        data=self.compiler();data['uncachedPipeline']['iterations']=4999
        with self.assertRaises(ValueError):verify_compiler(data)

    def fixture(self,folder):
        run=dict(status='PASS',matrixScope='FULL_MATRIX',originalCaseNames=['one','two'],rounds=30,
                 jarSha256='a'*64,certificateSha256='b'*64,executions=[])
        matrix=[dict(name='one'),dict(name='two')]
        expected={k:dict(rows=[['0','000001']]) for k in ('one','two')}
        for name in ('one','two'):
            for n in range(1,31):
                timing=dict(dorisExecutionMillis=n,totalMillis=n+10)
                details=dict(sourceValidationMillis=1,mainExplainMillis=1,availabilityExplainMillis=1,missingStatisticsMillis=2,sampleDetailsMillis=3)
                file=f'{name}-{n}.json'
                data=dict(rows=expected[name]['rows'],truncated=False,timings=timing,
                          dataQuality=dict(certificateSha256=run['certificateSha256'],diagnosticTimings=details),
                          limits=dict(queryTimeoutSeconds=10,maxExecutionMemoryBytes=2147483648,maxEstimatedScanRows=100000000,maxReturnRows=10000))
                (folder/file).write_text(json.dumps(data))
                run['executions'].append(dict(case=name,round=n,phase='timed',status='PASS',checks=dict(rowsEqual=True),
                    timings=timing,diagnosticTimings=details,wallMillis=n+12,artifact=file))
        for file,data in [('matrix.json',matrix),('expected.json',expected),('result.json',run)]:
            (folder/file).write_text(json.dumps(data))
        return run

    def test_full_matrix_has_separate_phase_percentiles(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);self.fixture(folder);summary=summarize(folder)
            self.assertEqual(2,len(summary['cases']))
            self.assertEqual(29,summary['cases'][0]['mainSql']['p95'])
            self.assertEqual('NOT_AVAILABLE_IN_SUMMARY',summary['cases'][0]['queryPeakMemoryStatus'])

    def test_partial_cases_duplicate_rounds_wrong_budget_and_forged_rows_rejected(self):
        for corruption in ('missing-case','duplicate-round','subset','wrong-budget','forged-rows','forged-time'):
            with self.subTest(corruption=corruption),tempfile.TemporaryDirectory() as temp:
                folder=Path(temp);run=self.fixture(folder)
                if corruption=='missing-case':run['executions']=[e for e in run['executions'] if e['case']=='one']
                elif corruption=='duplicate-round':run['executions'][0]['round']=2
                elif corruption=='subset':run['matrixScope']='TIMING_SUBSET'
                else:
                    path=folder/run['executions'][0]['artifact'];data=json.loads(path.read_text())
                    if corruption=='wrong-budget':data['limits']['maxExecutionMemoryBytes']*=2
                    elif corruption=='forged-rows':data['rows']=[]
                    else:data['timings']['totalMillis']=1
                    path.write_text(json.dumps(data))
                (folder/'result.json').write_text(json.dumps(run))
                with self.assertRaises(ValueError):summarize(folder)


if __name__=='__main__':unittest.main()
