package cn.hm.repolens.messaging;
import cn.hm.repolens.domain.ControlClock;
import cn.hm.repolens.persistence.ControlMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
@Service
public class EventConsumer {
 private final ControlMapper db;private final ControlClock time;private final AgentWakeClient worker;
 public EventConsumer(ControlMapper db,ControlClock time,AgentWakeClient worker){this.db=db;this.time=time;this.worker=worker;}
 @Transactional(rollbackFor=Exception.class)
 public void consume(String id,String topic,String aggregate,String payload)throws Exception{
  if(db.received("repolens-worker",id)>0)return;
  switch(topic){case "AGENT_JOB_CREATED"->worker.wake(aggregate);case "AGENT_JOB_CANCELLED"->worker.cancel(aggregate);default->throw new IllegalArgumentException("Unknown task event");}
  db.receipt("repolens-worker",id,time.now());
 }
}
