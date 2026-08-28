# PrisHistorie - Kubernetes

Local Kubernetes setup for PrisHistorie using:

- kind
- Cilium
- Cilium Ingress
- SQLite on a PersistentVolumeClaim
- Kubernetes CronJob

The cluster consists of one control-plane node and two worker nodes.

## Prerequisites

The following tools must be installed:

```powershell
docker --version
kubectl version --client
kind version
helm version
```

Docker Desktop must be running.

---

## 1. Create the kind cluster

The cluster configuration is located at:

```text
kubernetes/cluster.yaml
```

The cluster disables both kind's default CNI and `kube-proxy`.

Cilium will provide the cluster networking and Kubernetes Service routing.

Relevant configuration:

```yaml
networking:
  disableDefaultCNI: true
  kubeProxyMode: "none"
```

The control-plane node also exposes the NodePorts used by Cilium Ingress:

```yaml
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 31072
        hostPort: 31072
        protocol: TCP
      - containerPort: 31063
        hostPort: 31063
        protocol: TCP

  - role: worker
  - role: worker
```

Create the cluster:

```powershell
kind create cluster `
  --name prishistorie `
  --config .\kubernetes\cluster.yaml
```

At this point the nodes may be `NotReady`.

This is expected because no CNI has been installed yet.

---

## 2. Install Cilium

Cilium provides:

- Pod networking (CNI)
- Kubernetes Service routing
- kube-proxy replacement
- Ingress

Because `kube-proxy` is disabled, Cilium must be told how to reach the Kubernetes API server directly.

### Get the Kubernetes API server IP

The Kubernetes API server runs inside the kind control-plane container on port `6443`.

Get the control-plane container's IP address:

```powershell
$API_SERVER_IP = docker inspect `
  -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' `
  prishistorie-control-plane
```

Verify the value:

```powershell
$API_SERVER_IP
```

Example:

```text
172.21.0.4
```

Do not hardcode this IP address. Docker may assign a different IP when the cluster is recreated.

`kubectl cluster-info` may show an address such as:

```text
https://127.0.0.1:63343
```

That is the Windows host address and dynamically assigned port mapped into the kind control-plane container.

Cilium runs inside the kind environment and therefore uses the control-plane container IP and port `6443`.

The path is effectively:

```text
Cilium
   |
   | https://<control-plane-container-ip>:6443
   v
Kubernetes API Server
```

### Install Cilium with Helm

Add the Cilium Helm repository:

```powershell
helm repo add cilium https://helm.cilium.io/
helm repo update
```

Install Cilium:

```powershell
helm install cilium cilium/cilium `
  --namespace kube-system `
  --set kubeProxyReplacement=true `
  --set k8sServiceHost=$API_SERVER_IP `
  --set k8sServicePort=6443 `
  --set ingressController.enabled=true `
  --set ingressController.loadbalancerMode=dedicated
```

Important settings:

- `kubeProxyReplacement=true` makes Cilium handle Kubernetes Service routing instead of `kube-proxy`.
- `k8sServiceHost` tells Cilium where the Kubernetes API server can be reached.
- `k8sServicePort=6443` is the API server port inside the kind control-plane container.
- `ingressController.enabled=true` enables Cilium Ingress.
- `ingressController.loadbalancerMode=dedicated` gives the Ingress its own service.

### Verify Cilium

Watch the system pods:

```powershell
kubectl get pods -n kube-system -w
```

Press `Ctrl+C` when Cilium and CoreDNS are running.

Verify the nodes:

```powershell
kubectl get nodes
```

All three nodes should eventually show:

```text
Ready
```

Verify that `kube-proxy` is not running:

```powershell
kubectl get pods -n kube-system | Select-String "kube-proxy"
```

The command should return no results.

---

## 3. Verify storage

kind provides the default `standard` StorageClass using the local-path provisioner.

Verify it:

```powershell
kubectl get storageclass
```

Expected:

```text
NAME                 PROVISIONER
standard (default)   rancher.io/local-path
```

The SQLite PVC uses this StorageClass.

> The local kind volume is development storage, not a backup. Deleting the kind cluster may delete the database stored in the cluster.

---

## 4. Build and load the application images

Build the Docker images:

```powershell
docker compose build
```

The local Docker images are not automatically available inside kind.

Load both images into the cluster:

```powershell
kind load docker-image `
  prishistorie-prishistorie-api `
  --name prishistorie

kind load docker-image `
  prishistorie-prishistorie-cron `
  --name prishistorie
```

This must be repeated after rebuilding an image that should be deployed to the kind cluster.

---

## 5. Create the namespace

Create the PrisHistorie namespace:

```powershell
kubectl apply -f .\kubernetes\namespace.yaml
```

Verify:

```powershell
kubectl get namespaces
```

The following namespace should exist:

```text
prishistorie
```

---

## 6. Create secrets

`kubernetes/secret.example.yaml` contains the structure required by the application but must not contain real credentials.

Example:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: prishistorie-secrets
  namespace: prishistorie
type: Opaque
stringData:
  KJORETOY_API_KEY: "<api-key>"
  RECIPIENT_EMAIL: "<recipient-email>"
  SMTP_SERVER: "smtp.gmail.com"
  SMTP_PORT: "587"
  SENDER_EMAIL: "<sender-email>"
  SENDER_PASSWORD: "<password>"
```

Create a local copy:

```powershell
Copy-Item `
  .\kubernetes\secret.example.yaml `
  .\kubernetes\secret.local.yaml
```

Edit `secret.local.yaml` and replace the placeholders with the real values.

The local file must be excluded from Git:

```gitignore
kubernetes/secret.local.yaml
```

Apply the Secret:

```powershell
kubectl apply -f .\kubernetes\secret.local.yaml
```

Verify that it exists:

```powershell
kubectl get secret -n prishistorie
```

Do not commit `secret.local.yaml`.

Base64 encoding Kubernetes Secret values does not make the values secure or encrypted.

---

## 7. Create persistent storage

Create the PVC:

```powershell
kubectl apply -f .\kubernetes\pvc.yaml
```

Create the helper pod that mounts the PVC:

```powershell
kubectl apply -f .\kubernetes\pvc-loader.yaml
```

Verify:

```powershell
kubectl get pvc -n prishistorie
kubectl get pod -n prishistorie pvc-loader
```

Expected state:

```text
prishistorie-data   Bound
pvc-loader          Running
```

The StorageClass uses `WaitForFirstConsumer`, so the PVC may initially show `Pending` until a Pod such as `pvc-loader` uses it.

`pvc-loader` is only a utility Pod for copying files to and from the PVC. It is not part of the application itself.

---

## 8. Import the SQLite database

Import the database **before deploying the API and CronJob**.

This prevents the application from reading or writing the database while it is being replaced.

Assuming the backup is:

```text
PrisHistorie-backup.db
```

copy it into the PVC:

```powershell
kubectl cp `
  .\PrisHistorie-backup.db `
  prishistorie/pvc-loader:/data/PrisHistorie.db
```

Verify:

```powershell
kubectl exec `
  -n prishistorie `
  pvc-loader `
  -- ls -lh /data
```

`PrisHistorie.db` should now exist under `/data`.

The API and CronJob mount this PVC at:

```text
/app/data
```

so the application sees the database as:

```text
/app/data/PrisHistorie.db
```

---

## 9. Deploy the API

Deploy the API:

```powershell
kubectl apply -f .\kubernetes\api.yaml
```

Deploy the internal Service:

```powershell
kubectl apply -f .\kubernetes\service.yaml
```

Deploy Cilium Ingress:

```powershell
kubectl apply -f .\kubernetes\ingress.yaml
```

Verify:

```powershell
kubectl get pods -n prishistorie
kubectl get svc -n prishistorie
kubectl get ingress -n prishistorie
```

The API Pod should be `Running` and `Ready`.

### Test the API directly

For debugging, the internal Service can be temporarily exposed using port-forward:

```powershell
kubectl port-forward `
  -n prishistorie `
  svc/prishistorie-api `
  8000:8000
```

Then test:

```text
http://127.0.0.1:8000/CheckServer
```

Stop port-forward with `Ctrl+C`.

Port-forward is only a debugging mechanism and is not the normal application entry point.

---

## 10. Verify Cilium Ingress

The normal local entry point is:

```text
http://localhost:31072/CheckServer
```

Expected response:

```json
{
  "message": "Server is running"
}
```

The request path is:

```text
Windows
   |
   | localhost:31072
   v
Docker / kind port mapping
   |
   v
Cilium Ingress NodePort
   |
   v
Ingress rule
   |
   v
prishistorie-api Service :8000
   |
   v
API Pod :8000
   |
   v
SQLite PVC
```

Port `31072` is configured as the HTTP NodePort.

Port `31063` is reserved for HTTPS.

---

## 11. Deploy the CronJob

Before deploying, ensure `cronjob.yaml` contains the required environment configuration.

Secrets are loaded from:

```yaml
envFrom:
  - secretRef:
      name: prishistorie-secrets
```

Email alerts are application configuration rather than a secret and should be configured explicitly:

```yaml
env:
  - name: EMAIL_ALERTS_ENABLED
    value: "true"
```

Deploy the CronJob:

```powershell
kubectl apply -f .\kubernetes\cronjob.yaml
```

Verify:

```powershell
kubectl get cronjob -n prishistorie
```

The CronJob schedule is:

```text
0 9,10,14,18,22 * * *
```

with:

```text
Europe/Oslo
```

as the configured timezone.

---

## 12. Test the CronJob manually

A CronJob normally waits until its scheduled time.

To test it immediately, create a Job from the CronJob:

```powershell
kubectl create job `
  --from=cronjob/prishistorie-cron `
  prishistorie-cron-test `
  -n prishistorie
```

Watch the Job and Pod:

```powershell
kubectl get jobs,pods -n prishistorie
```

Follow the logs:

```powershell
kubectl logs `
  -f `
  -n prishistorie `
  job/prishistorie-cron-test
```

`Ctrl+C` stops following the logs. It does not stop the Job.

After a successful test, delete the manual Job:

```powershell
kubectl delete job `
  prishistorie-cron-test `
  -n prishistorie
```

The scheduled CronJob remains unaffected.

---

## 13. Back up the SQLite database

The `pvc-loader` Pod can also be used to copy the database out of Kubernetes:

```powershell
kubectl cp `
  prishistorie/pvc-loader:/data/PrisHistorie.db `
  .\PrisHistorie-backup.db
```

Avoid copying the database while the CronJob is writing to it.

If SQLite is using WAL mode, recent changes may exist in the WAL file rather than only in the main `.db` file. For a consistent backup, ensure there is no active writer before copying the database.

The PVC must not be treated as a backup. Back up important data before deleting or recreating the kind cluster.

---

## 14. Updating the application

After changing application code, rebuild the Docker images:

```powershell
docker compose build
```

Load the updated images into kind:

```powershell
kind load docker-image `
  prishistorie-prishistorie-api `
  --name prishistorie

kind load docker-image `
  prishistorie-prishistorie-cron `
  --name prishistorie
```

Existing Pods do not automatically restart just because a new image with the same name was loaded.

Restart the API Deployment:

```powershell
kubectl rollout restart `
  deployment/prishistorie-api `
  -n prishistorie
```

Verify:

```powershell
kubectl rollout status `
  deployment/prishistorie-api `
  -n prishistorie
```

New Jobs created by the CronJob will use the image available on the node when they start.

---

## 15. Useful commands

Show PrisHistorie resources:

```powershell
kubectl get all -n prishistorie
```

Show PVCs:

```powershell
kubectl get pvc -n prishistorie
```

Show Ingress:

```powershell
kubectl get ingress -n prishistorie
```

Show API logs:

```powershell
kubectl logs `
  -n prishistorie `
  -l app=prishistorie-api `
  --tail=100
```

Show CronJobs:

```powershell
kubectl get cronjob -n prishistorie
```

Show Jobs and Pods:

```powershell
kubectl get jobs,pods -n prishistorie
```

Show Cilium:

```powershell
kubectl get pods -n kube-system
```

Verify that kube-proxy is absent:

```powershell
kubectl get pods -n kube-system |
  Select-String "kube-proxy"
```

---

## 16. Delete the local cluster

Before deleting the cluster, back up the SQLite database if it contains data that must be preserved.

Delete the cluster:

```powershell
kind delete cluster --name prishistorie
```

Deleting the kind cluster does not delete the Docker images stored on the Windows host, but data stored in the cluster's local PersistentVolume should be considered disposable unless it has been backed up.