import http from 'k6/http';
import {check} from 'k6';
import exec from 'k6/execution';
import {Counter} from 'k6/metrics';
const data=JSON.parse(open(__ENV.LOAD_INPUT));const conflicts=new Counter('idempotency_conflicts');
http.setResponseCallback(http.expectedStatuses(200,409));
export const options={scenarios:{queue:{executor:'shared-iterations',vus:20,iterations:200,maxDuration:'90s'}},thresholds:{checks:['rate==1'],http_req_failed:['rate==0']},summaryTrendStats:['min','med','p(95)','max']};
export default function(){
 const id=exec.scenario.iterationInTest%40;
 const payload={workspaceId:data.workspace,idempotencyKey:data.run+'-'+id,repoUrl:'https://github.com/pallets/click',commitSha:'934813e4d421071a1b3db3973c02fe2721359a6e',question:'Synthetic queue-only load; worker deliberately stopped.'};
 const params={headers:{Authorization:'Bearer '+data.token,'Content-Type':'application/json'}};
 const first=http.post(data.origin+'/api/agent/jobs',JSON.stringify(payload),params);
 const replay=http.post(data.origin+'/api/agent/jobs',JSON.stringify(payload),params);
 for(const r of [first,replay]){if(r.status===409)conflicts.add(1);check(r,{'accepted_or_concurrent_conflict':x=>x.status===200||x.status===409});}
 if(first.status===200&&replay.status===200)check(replay,{'same_key_same_job':r=>r.json('id')===first.json('id')});
}
export function handleSummary(summary){return {[__ENV.LOAD_OUTPUT]:JSON.stringify(summary,null,2)};}
