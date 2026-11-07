package cn.hm.repolens.persistence;
import cn.hm.repolens.domain.Rows.*;
import java.time.LocalDateTime;
import java.util.List;
import org.apache.ibatis.annotations.*;
/** Durable task outbox and independent user identities; no booking tables. */
public interface ControlMapper {
  default int outbox(
      String id, String topic, String aggregateId, String payload, LocalDateTime now) {
    return insertOutbox(
        id, topic, aggregateId, payload, now, cn.hm.repolens.domain.TraceContext.parent());
  }

  @Insert(
      "INSERT INTO"
          + " outbox_event(id,topic,aggregate_id,payload,status,attempts,available_at,created_at,trace_parent)"
          + " VALUES(#{id},#{topic},#{aggregateId},#{payload},'PENDING',0,#{now},#{now},#{parent})")
  int insertOutbox(
      @Param("id") String id,
      @Param("topic") String topic,
      @Param("aggregateId") String aggregateId,
      @Param("payload") String payload,
      @Param("now") LocalDateTime now,
      @Param("parent") String parent);

  @Select("SELECT trace_parent FROM outbox_event WHERE id=#{id}")
  String traceParent(String id);

  @Select(
      "SELECT * FROM outbox_event WHERE (status='PENDING' AND available_at<=#{now}) OR"
          + " (status='SENDING' AND lease_until<=#{now}) ORDER BY created_at LIMIT 100")
  List<Outbox> dispatchable(LocalDateTime now);

  @Update(
      "UPDATE outbox_event SET"
          + " status='SENDING',lease_token=#{token},lease_until=#{until},attempts=attempts+1 WHERE"
          + " id=#{id} AND ((status='PENDING' AND available_at<=#{now}) OR (status='SENDING' AND"
          + " lease_until<=#{now}))")
  int leaseEvent(
      @Param("id") String id,
      @Param("token") String token,
      @Param("now") LocalDateTime now,
      @Param("until") LocalDateTime until);

  @Update(
      "UPDATE outbox_event SET status='SENT',last_error=NULL WHERE id=#{id} AND status='SENDING'"
          + " AND lease_token=#{token}")
  int sent(@Param("id") String id, @Param("token") String token);

  @Update(
      "UPDATE outbox_event SET status=#{status},last_error=#{error},available_at=#{next} WHERE"
          + " id=#{id} AND status='SENDING' AND lease_token=#{token}")
  int retry(
      @Param("id") String id,
      @Param("token") String token,
      @Param("status") String status,
      @Param("error") String error,
      @Param("next") LocalDateTime next);

  @Select(
      "SELECT COUNT(*) FROM consumer_receipt WHERE consumer_name=#{consumer} AND event_id=#{id}")
  int received(@Param("consumer") String consumer, @Param("id") String id);

  @Insert("INSERT INTO consumer_receipt VALUES(#{consumer},#{id},#{now})")
  int receipt(
      @Param("consumer") String consumer, @Param("id") String id, @Param("now") LocalDateTime now);

  @Select("SELECT * FROM app_user WHERE id=#{id}")
  User user(String id);

  @Insert("INSERT INTO app_user VALUES(#{id},#{passwordHash},#{role})")
  int insertUser(User row);

}
