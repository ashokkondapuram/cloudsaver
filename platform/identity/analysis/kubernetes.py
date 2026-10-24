"""Published Kubernetes review contracts; thresholds are fixed safety contracts."""
DEFINITIONS = (
    ('K8S_CONTAINER_CPU_OVERREQUEST','compute','kubernetes.io/Container','Container CPU request rightsizing review','cost'),
    ('K8S_CONTAINER_MEMORY_OVERREQUEST','compute','kubernetes.io/Container','Container memory working-set rightsizing review','cost'),
    ('K8S_CONTAINER_UNDERPROVISIONED_RISK','compute','kubernetes.io/Container','Throttling, OOM and QoS reliability review','reliability'),
    ('K8S_HPA_PDB_CONFLICT_OR_IDLE_FLOOR','compute','kubernetes.io/HorizontalPodAutoscaler','Autoscaler floor and PDB lock review','operations'),
    ('K8S_NODE_POOL_FRAGMENTATION_WASTE','compute','kubernetes.io/Node','Node capacity reservation slack review','cost'),
    ('K8S_ABANDONED_WORKLOAD_OR_NAMESPACE','compute','kubernetes.io/Container','Zero-traffic workload review','operations'),
    ('K8S_PVC_UNMOUNTED_OR_LOW_OCCUPANCY','storage','kubernetes.io/PersistentVolumeClaim','Unmounted or low-occupancy PVC review','cost'),
    ('K8S_STATEFULSET_SIZING_AND_VOLUME_TEMPLATE','compute','kubernetes.io/StatefulSet','Stateful memory buffer and ordinal volume review','reliability'),
    ('K8S_DAEMONSET_CLUSTER_WIDE_OVERHEAD_TAX','compute','kubernetes.io/DaemonSet','Observed DaemonSet fleet allocation slack','cost'),
    ('K8S_ORPHANED_LOADBALANCER_SERVICE','network','kubernetes.io/Service','Empty-endpoint LoadBalancer service review','cost'),
)
