{{/*
Resource name for a given service entry.
*/}}
{{- define "ragleap-app-chart.serviceName" -}}
{{- printf "%s-%s" .Release.Name .service.name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels for a given service entry.
*/}}
{{- define "ragleap-app-chart.serviceLabels" -}}
app: {{ .service.name }}
release: {{ .Release.Name }}
managed-by: ragleap-app-chart
{{- end -}}

{{/*
Resolve resources block: per-service override, else chart-level default.
*/}}
{{- define "ragleap-app-chart.resources" -}}
{{- if .service.resources -}}
{{ toYaml .service.resources }}
{{- else -}}
{{ toYaml .Values.defaultResources }}
{{- end -}}
{{- end -}}

{{/*
Resolve securityContext block: per-service override, else chart-level default.
*/}}
{{- define "ragleap-app-chart.securityContext" -}}
{{- if .service.securityContext -}}
{{ toYaml .service.securityContext }}
{{- else -}}
{{ toYaml .Values.defaultSecurityContext }}
{{- end -}}
{{- end -}}
