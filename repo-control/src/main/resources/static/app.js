import {createApp} from "/vendor/vue.js";
import {consumeEventStream} from "/event-stream.js";
createApp({data(){return {account:JSON.parse(sessionStorage.getItem("repolens.account")||"null"),username:"alice",password:"",page:"agent",busy:false,error:"",notice:"",accountEpoch:0,workspaces:[],workspaceName:"",jobs:[],agent:{workspace:"",repo:"",commit:"",question:""},selectedJob:null,agentEvents:[],approval:null,report:null,followupQuestion:"",uploadStatus:"",uploadedArchive:null,streamController:null,streamJobId:null,labels:{QUEUED:"任务已排队",RUNNING:"调研中",AWAITING_APPROVAL:"等待确认",COMPLETED:"已完成",FAILED:"失败",CANCELLED:"已取消"}};},methods:{
    async api(path, options = {}, agent = false) {
      const epoch = this.accountEpoch;
      const headers = {
        "Content-Type": "application/json",
        ...(this.account
          ? { Authorization: "Bearer " + this.account.accessToken }
          : {}),
        ...options.headers,
      };
      const response = await fetch((agent ? "/agent" : "/api") + path, {
        ...options,
        headers,
      });
      if (epoch !== this.accountEpoch) throw Error("会话已切换，请重新操作");
      if (!response.ok) {
        let message = "服务暂不可用";
        try {
          const body = await response.json();
          message = body.message || body.detail || message;
        } catch {}
        if (response.status === 401 && this.account) {
          this.logout();
        }
        throw Error(message);
      }
      return response.status === 204 ? null : response.json();
    },
    async action(fn) {
      this.error = "";
      this.busy = true;
      try {
        return await fn();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },
    async login() {
      await this.action(async () => {
        this.account = await this.api("/auth/login", {
          method: "POST",
          body: JSON.stringify({
            username: this.username,
            password: this.password,
          }),
        });
        this.accountEpoch++;
        sessionStorage.setItem("repolens.account", JSON.stringify(this.account));
        this.password = "";
        await this.refresh();
      });
    },
    async stableKey(slot, body) {
      const epoch = this.accountEpoch,
        user = this.account?.user;
      if (!user) throw Error("请先登录");
      const encoded = new TextEncoder().encode(JSON.stringify(body)),
        digest = await crypto.subtle.digest("SHA-256", encoded),
        signature = Array.from(new Uint8Array(digest), (n) =>
          n.toString(16).padStart(2, "0"),
        ).join("");
      if (epoch !== this.accountEpoch || this.account?.user !== user)
        throw Error("会话已切换，请重新操作");
      const name = "repolens.pending-requests:" + user;
      let keys = {};
      try {
        keys = JSON.parse(sessionStorage.getItem(name) || "{}");
      } catch {}
      if (!keys[slot] || keys[slot].signature !== signature)
        keys[slot] = { signature, key: crypto.randomUUID() };
      sessionStorage.setItem(name, JSON.stringify(keys));
      return keys[slot].key;
    },
    releaseKey(slot) {
      const name = "repolens.pending-requests:" + this.account.user;
      let keys = {};
      try {
        keys = JSON.parse(sessionStorage.getItem(name) || "{}");
      } catch {}
      delete keys[slot];
      sessionStorage.setItem(name, JSON.stringify(keys));
    },
    async newWorkspace() {
      await this.action(async () => {
        await this.api("/agent/workspaces", {
          method: "POST",
          body: JSON.stringify({ name: this.workspaceName }),
        });
        this.workspaceName = "";
        await this.refresh();
      });
    },
    async createJob() {
      await this.action(async () => {
        const input = {
            workspaceId: this.agent.workspace,
            repoUrl: this.agent.repo,
            commitSha: this.agent.commit,
            question: this.agent.question,
          },
          key = await this.stableKey("new-agent-job", input);
        const j = await this.api("/agent/jobs", {
          method: "POST",
          body: JSON.stringify({ ...input, idempotencyKey: key }),
        });
        this.releaseKey("new-agent-job");
        this.notice = "任务已受理";
        await this.refresh();
        await this.inspectJob(j);
      });
    },
    async inspectJob(j) {
      j = this.jobs.find((x) => x.id === j.id) || j;
      const same = this.selectedJob?.id === j.id;
      this.selectedJob = j;
      let fetched = [],
        after = same ? Math.max(0, ...this.agentEvents.map((e) => e.seq)) : 0;
      for (let page = 0; page < 20; page++) {
        const batch = await this.api(
          "/jobs/" + j.id + "/events?after=" + after,
          {},
          true,
        );
        if (this.selectedJob?.id !== j.id) return;
        fetched.push(...batch);
        if (batch.length < 100) break;
        after = batch.at(-1).seq;
      }
      this.agentEvents = [
        ...new Map(
          [...(same ? this.agentEvents : []), ...fetched].map((e) => [
            e.seq,
            e,
          ]),
        ).values(),
      ].sort((a, b) => a.seq - b.seq);
      this.approval = null;
      if (j.status === "AWAITING_APPROVAL") {
        const approval = await this.api(
          "/jobs/" + j.id + "/approval",
          {},
          true,
        );
        if (this.selectedJob?.id !== j.id) return;
        this.approval = approval;
      }
      if (!same) this.report = null;
      if (j.status === "COMPLETED") {
        try {
          const report = await this.api("/jobs/" + j.id + "/report", {}, true);
          if (this.selectedJob?.id === j.id) this.report = report;
        } catch (e) {
          if (!e.message.includes("尚未就绪")) throw e;
        }
      }
      if (["COMPLETED", "CANCELLED", "FAILED"].includes(j.status))
        this.stopStream();
      else if (this.streamJobId !== j.id) this.startStream(j.id);
    },
    stopStream() {
      this.streamController?.abort();
      this.streamController = null;
      this.streamJobId = null;
    },
    async startStream(id) {
      this.stopStream();
      const control = new AbortController();
      this.streamController = control;
      this.streamJobId = id;
      let cursor = Math.max(0, ...this.agentEvents.map((e) => e.seq));
      while (!control.signal.aborted && this.account && this.page === "agent") {
        try {
          const response = await fetch(
            "/agent/jobs/" + id + "/stream?after=" + cursor,
            {
              headers: {
                Authorization: "Bearer " + this.account.accessToken,
                "Last-Event-ID": String(cursor),
              },
              signal: control.signal,
            },
          );
          if (!response.ok) throw Error("事件连接暂不可用");
          cursor = await consumeEventStream(
            response,
            cursor,
            control.signal,
            (event) => {
              cursor = event.seq;
              if (
                !this.agentEvents.some((existing) => existing.seq === event.seq)
              )
                this.agentEvents.push(event);
            },
          );
        } catch (e) {
          if (control.signal.aborted) return;
        }
        if (!control.signal.aborted)
          await new Promise((r) => setTimeout(r, 2000));
      }
    },
    async followup() {
      if (!this.followupQuestion?.trim()) return;
      await this.action(async () => {
        const slot = "followup:" + this.selectedJob.id,
          key = await this.stableKey(slot, { question: this.followupQuestion });
        const child = await this.api(
          "/agent/jobs/" + this.selectedJob.id + "/followup",
          {
            method: "POST",
            body: JSON.stringify({
              idempotencyKey: key,
              question: this.followupQuestion,
            }),
          },
        );
        this.releaseKey(slot);
        this.followupQuestion = "";
        await this.refresh();
        await this.inspectJob(child);
      });
    },
    async download(path, filename) {
      const response = await fetch("/agent" + path, {
        headers: { Authorization: "Bearer " + this.account.accessToken },
      });
      if (!response.ok || response.status === 204)
        throw Error("未收到文件内容，请检查下载工具或连接后重试");
      const blob = await response.blob();
      if (!blob.size) throw Error("未收到文件内容，请重试");
      const url = URL.createObjectURL(blob),
        link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    },
    async downloadArchive() {
      await this.action(async () => {
        const data = await this.api(
          "/uploads/" + this.uploadedArchive.id + "/content",
          {},
          true,
        );
        if (data.encoding !== "base64" || data.size < 1 || data.size > 12000000)
          throw Error("资料内容格式异常");
        const raw = atob(data.content),
          bytes = Uint8Array.from(raw, (c) => c.charCodeAt(0)),
          sha = Array.from(
            new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
            (n) => n.toString(16).padStart(2, "0"),
          ).join("");
        if (bytes.length !== data.size || sha !== data.sha256)
          throw Error("资料校验失败，未生成下载文件");
        const url = URL.createObjectURL(
            new Blob([bytes], { type: "application/zip" }),
          ),
          link = document.createElement("a");
        link.href = url;
        link.download = "reference.zip";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      });
    },
    async exportReport() {
      await this.action(async () => {
        const file = await this.api(
          "/jobs/" + this.selectedJob.id + "/export",
          { method: "POST", body: "{}" },
          true,
        );
        await this.download(
          "/jobs/" + this.selectedJob.id + "/artifacts/" + file.id,
          "research-report.json",
        );
      });
    },
    async uploadArchive(event) {
      const file = event.target.files?.[0];
      if (!file) return;
      event.target.value = "";
      this.uploadedArchive = null;
      this.uploadStatus = "正在读取资料包";
      await this.action(async () => {
        if (file.size > 12000000) throw Error("资料包最大12MB");
        const hash = async (bytes) =>
          Array.from(
            new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
            (n) => n.toString(16).padStart(2, "0"),
          ).join("");
        const bytes = await file.arrayBuffer(),
          sha = await hash(bytes);
        let state = await this.api(
          "/uploads",
          {
            method: "POST",
            body: JSON.stringify({
              workspace: this.agent.workspace,
              size: file.size,
              sha256: sha,
            }),
          },
          true,
        );
        state = await this.api("/uploads/" + state.id, {}, true);
        if (state.status !== "COMPLETED") {
          for (let offset = 0; offset < file.size; offset += state.part_size) {
            const part = offset / state.part_size + 1;
            if (state.parts.some((p) => p.part === part)) continue;
            this.uploadStatus = "正在上传第 " + part + " 片";
            const block = bytes.slice(offset, offset + state.part_size);
            await this.api(
              "/uploads/" + state.id + "/parts/" + part,
              {
                method: "PUT",
                headers: {
                  "Content-Type": "application/octet-stream",
                  "X-Content-Sha256": await hash(block),
                },
                body: block,
              },
              true,
            );
          }
          state = await this.api(
            "/uploads/" + state.id + "/complete",
            { method: "POST", body: "{}" },
            true,
          );
        }
        this.uploadedArchive = state;
        this.uploadStatus = "已完成上传和完整性校验";
        this.notice = "资料包已保存，重新选择同一文件可继续未完成的上传";
      });
    },
    eventText(e) {
      return (
        e.data.status ||
        e.data.name ||
        e.data.error ||
        e.data.commit ||
        e.data.snapshot?.slice(0, 12) ||
        ""
      );
    },
    async decide(approved) {
      await this.action(async () => {
        await this.api(
          "/jobs/" + this.selectedJob.id + "/approval",
          {
            method: "POST",
            body: JSON.stringify({
              plan_hash: this.approval.plan_hash,
              approval_nonce: this.approval.approval_nonce || "",
              approved,
            }),
          },
          true,
        );
        this.approval = null;
        await this.refresh();
      });
    },
    async renewApproval() {
      await this.action(async () => {
        this.approval = await this.api(
          "/jobs/" + this.selectedJob.id + "/approval/renew",
          {
            method: "POST",
            body: JSON.stringify({ plan_hash: this.approval.plan_hash }),
          },
          true,
        );
        this.notice = "计划已重新展示，请核对后决定是否批准。";
      });
    },
    async retryJob(j) {
      await this.action(async () => {
        await this.api("/agent/jobs/" + j.id + "/retry", { method: "POST" });
        await this.refresh();
      });
    },
    async cancelJob(j) {
      await this.action(async () => {
        await this.api("/agent/jobs/" + j.id + "/cancel", { method: "POST" });
        await this.refresh();
      });
    },
    logout(){this.accountEpoch++;this.stopStream();this.account=null;sessionStorage.removeItem("repolens.account");this.workspaces=[];this.jobs=[];this.selectedJob=null;this.agentEvents=[];this.approval=null;this.report=null;this.agent={workspace:"",repo:"",commit:"",question:""};this.uploadedArchive=null;this.uploadStatus="";this.followupQuestion="";this.notice="";this.error="";},
    async refresh(){if(!this.account)return;await this.action(async()=>{this.workspaces=await this.api("/agent/workspaces");this.jobs=await this.api("/agent/jobs");if(!this.agent.workspace&&this.workspaces.length)this.agent.workspace=this.workspaces[0].id;if(this.selectedJob)await this.inspectJob(this.selectedJob);});},
},mounted(){this.refresh();this.timer=setInterval(()=>{if(this.account&&!this.busy)this.refresh();},5000);},beforeUnmount(){clearInterval(this.timer);this.stopStream();}}).mount("#app");
