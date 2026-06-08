{{/*
Expand the name of the chart.
*/}}
{{- define "k8s-sentinel.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "k8s-sentinel.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "k8s-sentinel.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "k8s-sentinel.labels" -}}
helm.sh/chart: {{ include "k8s-sentinel.chart" . }}
{{ include "k8s-sentinel.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: k8s-sentinel
{{- end }}

{{- define "k8s-sentinel.selectorLabels" -}}
app.kubernetes.io/name: {{ include "k8s-sentinel.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app: k8s-sentinel
component: health-checker
{{- end }}

{{- define "k8s-sentinel.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "k8s-sentinel.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "k8s-sentinel.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else if .Values.secrets.create -}}
{{- printf "%s-secrets" (include "k8s-sentinel.fullname" .) -}}
{{- else if .Values.onepassword.enabled -}}
k8s-sentinel-secrets
{{- else -}}
{{- printf "%s-secrets" (include "k8s-sentinel.fullname" .) -}}
{{- end -}}
{{- end }}

{{- define "k8s-sentinel.image" -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end }}
