{{- define "ragleap-ops.labels" -}}
app.kubernetes.io/part-of: ragleap-core
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
