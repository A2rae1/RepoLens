package cn.hm.repolens.messaging;
import cn.hm.repolens.domain.ControlClock;
import cn.hm.repolens.persistence.ControlMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
/** Durable HTTP delivery for local development; not a RocketMQ integration claim. */
@Component @ConditionalOnProperty(name="app.messaging",havingValue="local",matchIfMissing=true)
public class LocalDispatcher {
 private final ControlMapper db;private final ControlClock time;private final EventConsumer consumer;
 public LocalDispatcher(ControlMapper db,ControlClock time,EventConsumer consumer){this.db=db;this.time=time;this.consumer=consumer;}
 @Scheduled(fixedDelay=700) public void tick(){
  for(var e:db.dispatchable(time.now())){String token=ControlClock.id();if(db.leaseEvent(e.id(),token,time.now(),time.now().plusSeconds(30))!=1)continue;
   try{consumer.consume(e.id(),e.topic(),e.aggregateId(),e.payload());db.sent(e.id(),token);}
   catch(Exception ex){db.retry(e.id(),token,e.attempts()>=9?"DEAD":"PENDING",ex.getClass().getSimpleName(),time.now().plusSeconds(Math.min(60,1L<<Math.min(e.attempts(),6))));}
  }
 }
}
