from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics import (
    TextAnalyticsClient,
    AnalyzeHealthcareEntitiesAction,
    RecognizePiiEntitiesAction,
)
import os
from azure.search.documents import SearchClient
from azure.appconfiguration.provider import (
    load,
    SettingSelector
)
import requests
import json
import openai
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential

# Connect to key vault
keyVaultName = "aisnomed-kv"
KVUri = f"https://{keyVaultName}.vault.azure.net"
credential = DefaultAzureCredential()
client = SecretClient(vault_url=KVUri, credential=credential)

# Get Keys
key = client.get_secret("textanalyticskey").value
endpoint = client.get_secret("textanalyticsep").value

searchkey = client.get_secret("cogsearchkey").value
searchendpoint = client.get_secret("cogsearchep").value
searchindex = client.get_secret("cogsearchindex").value

openaideployment = client.get_secret("azureopenaideployment").value
openai.api_type = "azure"
openai.api_base = client.get_secret("azureopenaiep").value
openai.api_version = "2023-05-15"
openai.api_key = client.get_secret("azureopenaikey").value

# Authenticate the text analytics for health client using key and endpoint 
def authenticate_client():
    ta_credential = AzureKeyCredential(key)
    text_analytics_client = TextAnalyticsClient(
            endpoint=endpoint, 
            credential=ta_credential)
    return text_analytics_client

# Authenticate the search client using key and endpoint 
def authenticate_search_client():
    s_credential = AzureKeyCredential(searchkey)
    search_client = SearchClient(
            endpoint=searchendpoint, 
            index_name=searchindex,
            credential=s_credential)
    return search_client


def index(request):
    print('Request for index page received')
    return render(request, 'hello_azure/index.html')

@csrf_exempt
def hello(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        outputstr=""
        mbsoutputstr=""
        documents = [name]
        client = authenticate_client()
        searchclient = authenticate_search_client()
        start_phrase = 'system: You are a helpful assistant.\n user: '
        prompt1= "Review the clinical note provided, marked up with suggested SNOMED codes and MBS codes and add any additional suggestions or corrections.  For each snomed code create a new line, add a link to the snomed reference website and suggest SNOMEDCT-AU Australian specific codes if applicable. For each MBS code, add a link to the MBS (Medicare Benefits Schedule) for that ItemNum.  For example MBS: 42485 would link to https://www9.health.gov.au/mbs/fullDisplay.cfm?type=item&qt=item&q=42845"
        
        if name is None or name == '':
            print("Request for hello page received with no name or blank name -- redirecting")
            return redirect('index')
        else:
            poller = client.begin_analyze_healthcare_entities(documents)
            result = poller.result()

            docs = [doc for doc in result if not doc.is_error]

            for idx, doc in enumerate(docs):
                for entity in doc.entities:
                    outputstr = outputstr + format(entity.text)
                    #outputstr = outputstr + " (" + format(entity.category) + ")"
                    if entity.category == "TreatmentName":
                      searchresults = searchclient.search(search_text=entity.text)
                      for result in searchresults:
                        mbsoutputstr = mbsoutputstr + "[[MBS: " + result["ItemNum"] +"]]\r\n"
                        break
                    if entity.data_sources is not None:
                      for data_source in entity.data_sources:
                        if (data_source.name == "SNOMEDCT_US"):
                          outputstr = outputstr + " [[SNOMED: " + data_source.entity_id + "]]"
                    outputstr = outputstr + "\r\n" + mbsoutputstr 
                
                    response = openai.ChatCompletion.create(
                        engine = openaideployment,
                        messages=[
                            {"role": "system", "content": "You are a helpful assistant."},
                            {"role": "user", "content": prompt1 + " \r\n" + outputstr}
                        ]
                    )

                    openairesponse = response['choices'][0]['message']['content']

            #print("Request for hello page received with name=%s" % name)
            context = {'name': openairesponse }
            return render(request, 'hello_azure/hello.html', context)
    else:
        return redirect('index')