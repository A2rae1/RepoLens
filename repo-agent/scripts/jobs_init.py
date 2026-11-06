"""Create the isolated scheduler database once; never reset existing state."""

import asyncio
import hashlib
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKER = Path(os.environ["LOCALAPPDATA"]) / "Programs/DockerDesktop/resources/bin/docker.exe"


async def sql(statement):
    p = await asyncio.create_subprocess_exec(
        str(DOCKER),
        "exec",
        "-i",
        "internship-projects-mysql-1",
        "sh",
        "-c",
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B',
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await p.communicate(statement.encode())
    if p.returncode:
        code = re.search(rb"ERROR ([0-9]+).*? at line ([0-9]+)", err)
        detail = f" code={code[1].decode()} line={code[2].decode()}" if code else ""
        raise RuntimeError("Own scheduler SQL failed (query/credentials omitted)" + detail)
    return out.decode().strip()


async def main():
    source = (ROOT / "infra/xxl-job/upstream-schema.sql").read_text(encoding="utf-8")
    ddl = source.split("INSERT INTO")[0].replace("`xxl_job`", "`xxl_job_project`")
    ddl = ddl.replace("CREATE TABLE `", "CREATE TABLE IF NOT EXISTS `")
    password = hashlib.md5(os.environ["XXL_ADMIN_PASSWORD"].encode()).hexdigest()
    ddl += "\nGRANT ALL PRIVILEGES ON xxl_job_project.* TO 'eventfulfill'@'%';\n"
    ddl += "INSERT INTO xxl_job_group(id,app_name,title,address_type,address_list,update_time) VALUES(1,'event-fulfill','Booking',0,NULL,NOW()) ON DUPLICATE KEY UPDATE id=id;\n"
    ddl += f"INSERT INTO xxl_job_user(id,username,password,role,permission) VALUES(1,'admin','{password}',1,NULL) ON DUPLICATE KEY UPDATE id=id;\n"
    ddl += "INSERT INTO xxl_job_lock(lock_name) VALUES('schedule_lock') ON DUPLICATE KEY UPDATE lock_name=lock_name;\n"
    ddl += "INSERT INTO xxl_job_info(id,job_group,job_desc,add_time,update_time,author,alarm_email,schedule_type,schedule_conf,misfire_strategy,executor_route_strategy,executor_handler,executor_param,executor_block_strategy,executor_timeout,executor_fail_retry_count,glue_type,glue_source,glue_remark,glue_updatetime,child_jobid,trigger_status,trigger_last_time,trigger_next_time) VALUES(1,1,'bookingReconcile',NOW(),NOW(),'project','', 'CRON','0/10 * * * * ?','FIRE_ONCE_NOW','ROUND','bookingReconcile','','SERIAL_EXECUTION',30,1,'BEAN','','project initialization',NOW(),'',0,0,0) ON DUPLICATE KEY UPDATE id=id;\nCOMMIT;"
    await sql(ddl)
    print("Isolated scheduler initialized; example jobs excluded, no credential printed.")


if __name__ == "__main__":
    asyncio.run(main())
