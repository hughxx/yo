# 发送消息给用户
welink-cli im send-to-user --receiver "user001" --text "Hello WeLink"

# 发送消息给群组
welink-cli im send-to-group --group-id "group001" --text "Group message"

# 查询历史消息
welink-cli im query-history-message --user-account "a0012345" --query-count 20
welink-cli im query-history-message --group-id "1234567891011" --query-count 20


help说明
Usage: welink-cli im [OPTIONS] SUBCOMMAND

Options:
  -h,--help                   Print this help message and exit

Subcommands:
  send-to-user                Send message to user

                              Description:
                                Send a text message to a single user. Currently supports sending to only
                                one user at a time.

                              Options:
                                --receiver: User account in format of pinyin initials + employee number
                                            (e.g., a0012345). Wrap in double quotes. If unsure of the
                                            account, use 'welink-cli search person' to find it and take
                                            the 'welinkid' field from the result.
                                --text:     Message text content. Wrap in double quotes.

                              Example:
                                welink-cli im send-to-user --receiver "a0012345" --text "hi"
  send-to-group               Send message to group

                              Description:
                                Send a text message to a single group. Currently supports sending to only
                                one group at a time.

                              Options:
                                --group-id: Group ID (numeric string). Wrap in double quotes.
                                --text:     Message text content. Wrap in double quotes.

                              Example:
                                welink-cli im send-to-group --group-id "1234567891011" --text "hi"
  create-group                Create a new group

                              Description:
                                Create a new group with specified members and settings.

                              Options:
                                --name:         Group name. Wrap in double quotes.
                                --user-account: Group member account(s) to add. Format: pinyin initials +
                                                employee number (e.g., a0012345). Wrap each account in
                                                double quotes. Separate multiple accounts with spaces.
                                --notice:     Group announcement/notice. Wrap in double quotes.
                                --type:         Group type (0: normal group, 1: discuss group). Default: 0.

                              Example:
                                welink-cli im create-group --name "test create group" --user-account "a0012345" "b0067890" --notice "test" --type 0
  query-recent-conversation   Query recent conversations

                              Description:
                                Query the most recent conversations for the current user.

                              Options:
                                --count: Number of recent conversations to query (1-50). Default: 10.

                              Example:
                                welink-cli im query-recent-conversation --count 20
  query-group-member          Query group members

                              Description:
                                Query the member list of a specific group.

                              Options:
                                --group-id: Group ID (numeric string). Wrap in double quotes.

                              Example:
                                welink-cli im query-group-member --group-id "1234567891011"
  query-history-message       Query message history

                              Description:
                                Query message history for a group or a user.

                              Options:
                                --group-id:     Group ID (for group chat). Wrap in double quotes.
                                --user-account: User account (for p2p chat). Format: pinyin initials +
                                                employee number (e.g., a0012345). Wrap in double quotes.
                                --query-count:  Number of messages to query (1-100). Default: 20.
                                --message-id:   Starting message ID. Default: 0.
                                --query-direction: Query direction (0: newer, 1: older). Default: 0.

                              Note: --group-id and --user-account are mutually exclusive. Specify one.

                              Examples:
                                welink-cli im query-history-message --user-account "a0012345"
                                welink-cli im query-history-message --group-id "1234567891011"
  add-group-member            Add members to the group

                              Description:
                                Add specified members to the group.

                              Options:
                                --group-id: Group ID (numeric string). Wrap in double quotes.
                                --user-account: Group member account(s) to add. Format: pinyin initials +
                                                employee number (e.g., a0012345). Wrap each account in
                                                double quotes. Separate multiple accounts with spaces.

                              Example:
                                welink-cli im add-group-member --group-id "1234567891011" --user-account "a0012345" "b0067890"



实例

C:\Users\w00899061>welink-cli im query-history-message --group-id "964044813181789425" --query-count 20
{
  "respData": {
    "chatInfo": [
      {
        "at": false,
        "atAccountList": [],
        "content": "{\"cardConfig\":{\"isForward\":false},\"cardContext\":{\"mergeMessage\":{\"fromName\":\"王啸虎\",\"level\":0,\"messageList\":[{\"account\":\"q00845593\",\"appServiceIcon\":\"\",\"appServiceName\":\"\",\"appServiceTag\":-1,\"isAppMsg\":0,\"mediaType\":0,\"msg\":\"不知道\\uff0c不管它\",\"msgId\":\"88929263171435822\",\"name\":\"乔龙威\",\"time\":1778585263428},{\"account\":\"w00899061\",\"appServiceIcon\":\"\",\"appServiceId\":\"w00899061\",\"appServiceInfo\":{\"appServiceName\":\"\"},\"appServiceName\":\"\",\"appServiceTag\":-1,\"isAppMsg\":1,\"mediaType\":0,\"msg\":\"hello welink\",\"msgId\":\"88931749702041263\",\"name\":\"王啸虎\",\"time\":1778634994040},{\"account\":\"q00845593\",\"appServiceIcon\":\"\",\"appServiceName\":\"\",\"appServiceTag\":-1,\"isAppMsg\":0,\"mediaType\":0,\"msg\":\"hello wink\",\"msgId\":\"88931753517016658\",\"name\":\"乔龙威\",\"time\":1778635070340},{\"account\":\"w00899061\",\"appServiceIcon\":\"\",\"appServiceName\":\"\",\"appServiceTag\":-1,\"isAppMsg\":0,\"mediaType\":0,\"msg\":\"[自动回复]有事不在\\uff0c请留言\",\"msgId\":\"88931753522987711\",\"name\":\"王啸虎\",\"time\":1778635070459}],\"toName\":\"乔龙威\",\"type\":1},\"replyMsg\":{\"type\":-1}},\"cardType\":19,\"isShowSource\":0}",
        "contentType": "CARD_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88931758028164113,
        "receiver": "",
        "sender": "w00899061",
        "serverSendTime": 1778635160563
      },
      {
        "at": false,
        "atAccountList": [],
        "content": "welink-cli支持查询历史消息：https://onebox.huawei.com/v/doconline/eyJvd25lcklkIjoyMDQ2MzEzOSwiZmlsZUlkIjoxOTksImxpbmtDb2RlIjoiNzZiYTg3NzY2ZDdlZGEzMWQyZWZhZmJmZGZmZDdlMTAiLCJ0eXBlIjoiMCIsInZpc2l0b3JJZCI6NjEyNTQxMX0",
        "contentType": "TEXT_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88931756778149515,
        "receiver": "",
        "sender": "w00899061",
        "serverSendTime": 1778635135562
      },
      {
        "at": false,
        "atAccountList": [],
        "content": "⁠/:Z",
        "contentType": "TEXT_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88931756234321311,
        "receiver": "",
        "sender": "w00899061",
        "serverSendTime": 1778635124686
      },
      {
        "at": false,
        "atAccountList": [],
        "content": "/:um_begin{https://clouddrive.huawei.com/f/58539aae6ff0402c69524bd281647655|File|2327|daili|0|;;9ef4765d91f5d97b6eae|isOriginalImg: 0;md5:28fe700efe080fc0715b40f07af93380;isCrossInstance:0;emotionId:;objectId:;cdnUrl:}/:um_end",
        "contentType": "FILE_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88931755892841861,
        "receiver": "",
        "sender": "w00899061",
        "serverSendTime": 1778635117856
      },
      {
        "at": false,
        "atAccountList": [],
        "content": "/:um_begin{https://clouddrive.huawei.com/f/6e55eaab5f646b57fa1fbbbe41a2cdff|Img|8645|EF9BE4D1-AAB3-4585-8367-AF202068CE1B.png|0|240;117;3ed6e6ec94231778d8dd|isOriginalImg: 0;md5:b0f3ccebd8173f6b11fc6d5cd1f15934;isCrossInstance:0;emotionId:;objectId:;cdnUrl:}/:um_end",
        "contentType": "PICTURE_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88931755311965610,
        "receiver": "",
        "sender": "w00899061",
        "serverSendTime": 1778635106239
      },
      {
        "at": false,
        "atAccountList": [],
        "content": "<div style=\"font-size:14px;\"><b>答案：</b><br><div style=\"margin-top:8px;\">你好！看起来你可能是想开始一段对话。如果你有任何问题或需要帮助，请随时告诉我，我会尽力为你提供帮助。😊</div><br><div style=\"margin-top:10px;border-top:1px solid;\"></div><div style=\"margin-top:10px;\"><b>参考资料：</b></div><div style=\"margin-top:10px;font-size:12px;\"><b>[1] 参考资料</b><br><span style=\"font-size:12px;\">https://shanhai.huawei.com/#/page-forum/post-details?postId=688586</span></div><div style=\"margin-top:10px;font-size:12px;\"></div></div>",
        "contentType": "TEXT_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88931752577508025,
        "receiver": "",
        "sender": "p_coreinsight",
        "serverSendTime": 1778635051550
      },
      {
        "at": false,
        "atAccountList": [],
        "content": "模型回答生成中...",
        "contentType": "TEXT_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88931752293285122,
        "receiver": "",
        "sender": "p_coreinsight",
        "serverSendTime": 1778635045865
      },
      {
        "at": true,
        "atAccountList": [],
        "content": "@云见 nihao",
        "contentType": "TEXT_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88931752245165513,
        "receiver": "",
        "sender": "w00899061",
        "serverSendTime": 1778635044903
      },
      {
        "at": false,
        "atAccountList": [],
        "content": "<r><n></n><g>1</g><c>H4sIAAAAAAAA/71VW28bRRT+K9sVEi9mL17jm6KoxgE1EoIKAn2IIjTePfYOnp1ZzczGdpGlAg9tQ1XEC5RWSCUKQjw08FAh1Fz+DFknPPUvcGbXsZu8VJWgL6uZc9tzvnPmOys06YlosroSCq6B69WVK5vdtc5GZ/MLW1PNwG7b+R/f5sf7p8d7+c5vs7vf2JVS8y5HXUfHwInVUYoqTbhGpRKZDOETSVGtQS1FeJ/9+Ozs66NFnJDIaGOSoibwy9t6hFbNZhC0ql5Qr/q1oNoKarW57ccgt2kIpYtXytaIJnYbsy2Ediciqabb0EWV8RJJKjgWpj4FqajgXRGhWa1iv6HCGBJ0tWOt07brkrmnCaocKtzSQC0UbxmN87kSHANvl+HQ3XfexvsIrgGJQBapzIGbPb79z+6D2fe38yc/FLkwgXq7xzIwoMRiZLf7hCmYGv8bNNIxqiPok4wZ2Exn7Pbmorb1hAyMZyYZ3vCQiB5lCDWbV6GwjFGQOHFGRkAdLN5NQiayyEVP97oU48l7QhZhXE35hBanbd8tDsqlERA3iLxaLwr8Vsv36n2oeRFp1YgXQDVoRATgs0a9OQ48z0n5AHNIw4v/Jyl1KOcgnREwyoevNZkRfEQimim77VcRYXrTwKa0BB3GBnJgEOpOqIvOLWemEDgfpsBNLecA84yxFwq8hLc9LezW/WYRCorv/9KQXtQiQLyw14de2KoHXq/V8CKISADNWguqr7Uhr5TMdDqtLFDegLF+h4lwaAgEz4ZZ9n7N9//Mfzl6fnhvdue72YPfS64pCeL54ZdFS7vzd7N8GPPGLgVYzyA2EXuCmUdYsWMh6U3kNMI6jA54ghSAagZ9Y56Q8fuUA44JTslIktRua5lBmdeLHbWv0Yq1/mZi3QB0GFol3V2x7JcUdvViHffOjg5mPx3ndx7lB8+QSE8ODvKdn0/+um/Ohw/P9vcNAI+e5nsPZzu3kCFPn9w9OXo8u797+nT371tfvTIMS9F/hMPVCwBULCCKsokVSiAarIEUWWppoobKEtJKAHB+BqpiJUKCpYaUMWWNCDVSq48WE5FZWlgwTrEmcBDOrWlJ513B+3Rg/hsSjuM4MjxesqQxQEo+z5Gqy2oMhw+/0fSr1YYXNL16fWqEWpLzJUHStNgwOPvnz2D+KEhRGGKCJoyGxDDCBySBLl9swMXaumRSLMISnxIeQw1UXe+uUZUyghTuT7e2VlfcxY5151v3X4Ut9EF+BwAA</c></r>",
        "contentType": "CARD_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88931751905769807,
        "receiver": "",
        "sender": "p_welinkathena",
        "serverSendTime": 1778635038115
      },
      {
        "at": false,
        "atAccountList": [],
        "content": "已升级为团队，解锁团队空间，现在里面空空如也，快来传个文档体验下吧",
        "contentType": "NOTICE_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88931751895278655,
        "receiver": "",
        "sender": "w00899061",
        "serverSendTime": 1778635037905
      }
    ],
    "maxMsgId": 88931758028164113,
    "minMsgId": 88931751895278655,
    "msgTotalCount": 10
  },
  "resultCode": "0",
  "resultContext": "Operate Success",
  "sno": null
}


提取图片和文件的代码：
parse_um_content(msg.input_text[len("/:um_begin{"):-len("}/:um_end")])

def parse_um_content(um_content):
    um_content_arr = um_content.split("|")
    download_url = um_content_arr[0]
    file_name = um_content_arr[3]
    field5 = um_content_arr[5].split(";")
    extraction_code = field5[2]
    image_file_info = one_box_download(download_url, extraction_code)
    ocr_result = ocr(image_file_info.file_content, file_name)
    img_url = img_to_url(image_file_info.file_content, file_name)
    return ocr_result, img_url

群聊里别人at我
{
        "at": true,
        "atAccountList": [
          "w00899061"
        ],
        "content": "@王啸虎 虎",
        "contentType": "TEXT_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88933654262715872,
        "receiver": "",
        "sender": "q00845593",
        "serverSendTime": 1778673085254
      },
      {
        "at": false,
        "atAccountList": [],
        "content": "加个字",
        "contentType": "TEXT_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88933653968099705,
        "receiver": "",
        "sender": "w00899061",
        "serverSendTime": 1778673079361
      },
      {
        "at": true,
        "atAccountList": [
          "w00899061"
        ],
        "content": "@王啸虎 ",
        "contentType": "TEXT_MSG",
        "groupId": 964044813181789425,
        "groupType": 0,
        "msgId": 88933653802718619,
        "receiver": "",
        "sender": "q00845593",
        "serverSendTime": 1778673076054
      },