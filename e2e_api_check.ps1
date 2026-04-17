$ErrorActionPreference = "Stop"
function Invoke-Api {
param([string]$Method,[string]$Url,[object]$Body=$null,[hashtable]$Headers=@{})
  $p=@{Method=$Method;Uri=$Url;Headers=$Headers;UseBasicParsing=$true;TimeoutSec=30}
  if($null -ne $Body){$p.Body=($Body|ConvertTo-Json -Depth 10);$p.ContentType='application/json'}
  try {
    $r=Invoke-WebRequest @p
    $j=$null
    try {$j=$r.Content|ConvertFrom-Json} catch {}
    return [pscustomobject]@{ok=$true;status=[int]$r.StatusCode;json=$j;raw=$r.Content}
  } catch {
    $resp=$_.Exception.Response
    if($resp){
      $sr=New-Object IO.StreamReader($resp.GetResponseStream())
      $c=$sr.ReadToEnd(); $sr.Close()
      $j=$null
      try {$j=$c|ConvertFrom-Json} catch {}
      return [pscustomobject]@{ok=$false;status=[int]$resp.StatusCode;json=$j;raw=$c}
    }
    return [pscustomobject]@{ok=$false;status=0;json=$null;raw=$_.Exception.Message}
  }
}

$base='http://127.0.0.1:8000'
$email="demo_$(Get-Date -Format yyyyMMddHHmmss)@gigshield.test"
$pass='Test@12345'
$phone='9' + (Get-Random -Minimum 100000000 -Maximum 999999999)
$reg=Invoke-Api -Method POST -Url "$base/api/v1/auth/register" -Body @{
  email=$email
  password=$pass
  phone=$phone
  name='Demo Rider'
  declared_income=1200
  city='Mumbai'
}
"register_status=$($reg.status)"
"register_has_token=$([bool]$reg.json.access_token)"
"register_has_rider_id=$([bool]$reg.json.rider_id)"
$token=$reg.json.access_token
$auth=@{Authorization="Bearer $token"}

$h=Invoke-Api -Method GET -Url "$base/api/v1/hubs?city=Mumbai" -Headers $auth
"hubs_status=$($h.status)"
$hubId=$null
if($h.json -and $h.json.hubs -and $h.json.hubs.Count -gt 0){$hubId=$h.json.hubs[0].id; "hubs_count=$($h.json.hubs.Count)"} else {"hubs_count=0"}
if(-not $hubId){$hubId='00000000-0000-0000-0000-000000000001'}

$cr=Invoke-Api -Method POST -Url "$base/api/v1/riders" -Headers $auth -Body @{name='Demo Rider';phone='9999999999';platform='zepto';city='Mumbai';declared_income=1200;hub_id=$hubId}
"create_rider_status=$($cr.status)"

$fund='fa_demo_manual_001'
$payout=Invoke-Api -Method POST -Url "$base/api/v1/riders/me/payout-destination" -Headers $auth -Body @{razorpay_fund_account_id=$fund}
"payout_destination_status=$($payout.status)"
"payout_has_fund_id=$([bool]$payout.json.razorpay_fund_account_id)"

$q=Invoke-Api -Method GET -Url "$base/api/v1/policies/quote?plan=standard&hub_id=$hubId" -Headers $auth
"quote_status=$($q.status)"
"quote_has_premium=$([bool]($q.json.premium_amount -ne $null))"

$pc=Invoke-Api -Method POST -Url "$base/api/v1/policies" -Headers $auth -Body @{plan='standard';hub_id=$hubId;razorpay_fund_account_id=$fund}
"create_policy_status=$($pc.status)"
$policyId=$pc.json.id

$l=Invoke-Api -Method GET -Url "$base/api/v1/dashboard/live" -Headers $auth
"dashboard_live_status=$($l.status)"
$pm=Invoke-Api -Method GET -Url "$base/api/v1/policies/me" -Headers $auth
"policies_me_status=$($pm.status)"
$rm=Invoke-Api -Method GET -Url "$base/api/v1/riders/me" -Headers $auth
"riders_me_status=$($rm.status)"
if($rm.json -and $rm.json.name){"rider_name=$($rm.json.name)"}
$rp=Invoke-Api -Method GET -Url "$base/api/v1/riders/me/payouts" -Headers $auth
"rider_payouts_status=$($rp.status)"
$ra=Invoke-Api -Method GET -Url "$base/api/v1/riders/me/activity" -Headers $auth
"rider_activity_status=$($ra.status)"
if($policyId){$pause=Invoke-Api -Method PATCH -Url "$base/api/v1/policies/$policyId/status" -Headers $auth -Body @{action='pause';reason='test'}; "policy_pause_status=$($pause.status)"}

$adLogin=Invoke-Api -Method POST -Url "$base/api/v1/auth/admin/login" -Body @{username='admin';password='GigShield@Admin123'}
"admin_login_status=$($adLogin.status)"
$at=$adLogin.json.access_token
$ah=@{Authorization="Bearer $at"}
$adDash=Invoke-Api -Method GET -Url "$base/internal/admin/dashboard" -Headers $ah
"admin_dashboard_status=$($adDash.status)"
$adClaims=Invoke-Api -Method GET -Url "$base/internal/admin/claims?page=1" -Headers $ah
"admin_claims_status=$($adClaims.status)"
$sim=Invoke-Api -Method POST -Url "$base/internal/admin/stress-test/run" -Headers $ah -Body @{city='Mumbai';trigger_type='rain';pct_riders_affected=0.3;avg_duration_hrs=2.0;avg_income=700;plan='standard';tier='B'}
"admin_sim_status=$($sim.status)"
