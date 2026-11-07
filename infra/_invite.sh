uid() {
  local id
  id="$(az ad user list --filter "mail eq '$1'" --query "[0].id" -o tsv 2>/dev/null)"
  if [[ -z "$id" ]]; then
    id="$(az rest --method post --url https://graph.microsoft.com/v1.0/invitations --body "{\"invitedUserEmailAddress\":\"$1\",\"inviteRedirectUrl\":\"https://portal.azure.com\",\"sendInvitationMessage\":true}" --query invitedUser.id -o tsv 2>/dev/null)"
    if [[ -n "$id" ]]; then echo "  ✉ undangan dikirim ke $1" >&2; sleep 20; fi
  fi
  echo "$id"
}
