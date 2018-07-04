# Imports
import random, time, requests
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urldefrag
Helper = projectRelativeImport('helpers', 'app/util', 'Helper')
ScrapedItem = projectRelativeImport('scrapedItem', 'app/modules/scraping', 'ScrapedItem')
StorageManager = projectRelativeImport('storageManager', 'app/modules/file-management', 'StorageManager')

# Main class to hold our data
class Data:
    # id of collector item currently being addressed
    currentId = -1
    # urls must contain base to be accepted, so 'bbc.com' would mean we only scrape urls from that page
    base = ''
    # the selector for getting the element which holds the content we want to save
    selector = 'body'

    # Initializer, adds our first collector item to our collector and sets the base url
    def __init__(self, selector, starter, baseUrl = ''):
        self.setPayload()

        # validate
        if baseUrl == '' or baseUrl is None:
            baseUrl = starter

        if selector != '' or selector is not None:
            self.selector = selector

        self.base = baseUrl
        # Holds result
        self.collector = []
        item = self.createCollectorItem(starter)
        self.addCollectorItem(item)

    def setPayload(self):
        print('requesting random agent from w3schools')
        agent = None
        try:
            agent = UserAgent().random
        except:
            print('request failed, using default agent')
            agent = 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1'

        print('agent: ' + agent)

        # request params
        self.payload = {
            'timeout': 60,
            'headers': {
                'User-Agent': agent
            }
        }

    # Creates a brand new unedited collector item and returns it
    def createCollectorItem(self, url):
        parentId = self.currentId
        return ScrapedItem.CollectorItem(parentId, url)

    # Adds supplied item to the end of our collector
    def addCollectorItem(self, item):
        item.id = len(self.collector) # next value in collector will be the index, which we will call id on the object
        self.collector.append(item)

    # Returns content from url wrapped in BeautifulSoup object
    def fetchUrl(self, url):
        t0 = time.time() # attempted request time
        response = requests.get(url, params=self.payload)
        self.responseDelay = time.time() - t0; # record response delay
        return BeautifulSoup(response.content, 'html.parser')

    def sleeper(self):
        sec = round(0.01+(10*self.responseDelay),2) # backoff if responseDelay is high
        print('Finished with currentItem ' + str(self.currentId) + '. Will now sleep for ' + str(sec) + ' seconds')
        time.sleep(sec) # don't want to get caught and ipbanned or other shiz. Lets take it steady
        self.setPayload() # new agent

    def contentExtract(self, currentItem, currentItemContent):
        currentItem.content = currentItemContent.find_all(self.selector)
        currentItem.title = currentItemContent.title
        if currentItem.title != None:
            currentItem.title = currentItem.title.string
        else:
            currentItem.title = ''

        currentItem.headerOne = currentItemContent.find('h1')
        if currentItem.headerOne != None:
            currentItem.headerOne = currentItem.headerOne.string
        else:
            currentItem.headerOne = ''

        return currentItem

    # Main Loop
    def start(self):
        # Loop while there are still items left ahead of our current id in self.collector
        # Alternative (more robust less efficient) condition `any(item.attempted == False for item in self.collector)`
        while (self.currentId+1 < len(self.collector)):
            self.currentId+=1
            try:
                currentItem = self.collector[self.currentId] # Does variable get set to loop scope or try scope? Testing will reveal
            except IndexError:
                raise IndexError('Missing item from self.collector at position ' + str(self.currentId) + ' in Data start(),'
                r' while condition should have ended loop before any index errors occour')

            print('Attempting currentItem ' + str(self.currentId) + ' with url ' + currentItem.url)

            if currentItem.attempted == True:
                raise ValueError('Invalid value of attempted in currentItem in Data start(), item at new id should never have already been attempted')

            # Attempt to fetch content from url
            try:
                currentItemContent = self.fetchUrl(currentItem.url)
                currentItem.attempted = True
            except:
                # if fetching raises an exception we still want to mark as attempted
                currentItem.attempted = True
                raise
            # Save changes
            self.collector[self.currentId] = currentItem

            # Create new items from found links
            for link in currentItemContent.find_all('a'):
                url = link.get('href')

                # Validate url
                if Helper.url_validate(url) == False:
                    url = urljoin(currentItem.url, url) #to handle relative path urls
                    if Helper.url_validate(url) == False:
                        continue

                # TODO check for redirects here
                url = urldefrag(url).url # remove fragmentation from url before checks

                # Check url is an extension of our base url
                if self.base not in url:
                    continue

                # Check we haven't already stored this url
                item = None # we want scope of item to be here. Value changes in if else. Value is used in if not after that
                selfReferencing = True
                if any(item.url == url for item in self.collector):
                    # we have already stored this url so now find the item using it and add current as parent
                    for item in self.collector:
                        if item.url == url and item.id != self.currentId:
                            selfReferencing = False
                            if self.currentId not in self.collector[item.id].parents: # if not already parent adds current id to parents on already existing item
                                self.collector[item.id].parents.append(self.currentId)

                            break # break out of loop so item keeps its value to be used outside this if else

                else:
                    # we haven't already stored this url so we must create an item for it
                    item = self.createCollectorItem(url) # creating collector item  handles parentId
                    self.addCollectorItem(item)

                if not selfReferencing and item.id not in currentItem.children:
                    # whether we have or havent stored this url before we must still add the child to currrent items child ids
                    # with the exception of when a page is linking to itself, aka don't add child if self referencing
                    # and also with the exception of if we already have the id listed as a child
                    currentItem.children.append(item.id)

            currentItem = self.contentExtract(currentItem, currentItemContent) # sets currentItem's content, headerOne and title

            # Save changes
            self.collector[self.currentId] = currentItem
            self.sleeper() # wait before making another request

        self.save()

    # We've crawled all possible urls and will now clean up.
    # TODO implement functionality to save while crawling (memory is important guys).
    # TODO cont... Maybe create a temp save handler which basicaly act as variables but in storage, should only hold content as the rest is required.
    # TODO cont... Better solution would likely be to use a database to hold what is currently self.collector[].
    def save(self):
        print('Attempting to save')
        storage = StorageManager.DataStorage(self.base)
        # Save collector items where saved == False
        indexes = [idx for idx, val in enumerate(self.collector) if val.saved == False]
        for index in indexes:
            if storage.saveItem(self.collector[index]):
                self.collector[index].saved = True
            else:
                self.collector[index].saved = False

            index+= 1

        print('Saved')
