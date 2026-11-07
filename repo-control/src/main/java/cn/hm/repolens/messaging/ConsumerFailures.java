package cn.hm.repolens.messaging;

import cn.hm.repolens.domain.ControlClock;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Observations are outside the failed business transaction, never its idempotency authority. */
@Repository
public class ConsumerFailures {
    private final JdbcTemplate jdbc;private final ControlClock time;
    public ConsumerFailures(JdbcTemplate jdbc,ControlClock time){this.jdbc=jdbc;this.time=time;}
    public void failed(String group,String event,int reconsume,Exception error){
        jdbc.update("INSERT INTO consumer_failure VALUES(?,?,1,?,?,'FAILED',?) ON DUPLICATE KEY UPDATE observations=observations+1,last_reconsume=?,error_class=?,status='FAILED',updated_at=?",
            group,event,reconsume,error.getClass().getSimpleName(),time.now(),reconsume,error.getClass().getSimpleName(),time.now());
    }
    public void resolved(String group,String event){jdbc.update("UPDATE consumer_failure SET status='RESOLVED',updated_at=? WHERE consumer_name=? AND event_id=?",time.now(),group,event);}
}
